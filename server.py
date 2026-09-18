"""
Telekom agentic commerce demo — MCP server.

A demonstration server for showing MCP-based commerce journeys inside Claude,
Gemini or ChatGPT. Nothing here calls a real Telekom system: every tool answers
from the markdown files in ./catalogue, so a product manager can change the
offer by editing a file and restarting.

Run locally:      python server.py
Run remote/HTTP:  python server.py --http --port 8000
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import segno
from mcp.server.apps import Apps, ResourceCsp, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents, ToolAnnotations

HERE = Path(__file__).parent
CATALOGUE = HERE / "catalogue"

APP_DOWNLOAD_URL = "https://www.telekom.de/meinmagenta-app"

# Emit the widget a second time as an in-band embedded `ui://` resource, which is
# how MCP-UI clients render. Costs a few KB per call on clients that ignore it;
# set TELEKOM_MCP_UI=0 to send structured output only.
MCP_UI_ENABLED = os.environ.get("TELEKOM_MCP_UI", "1").strip().lower() not in ("0", "false", "no", "off")

# --------------------------------------------------------------------------
# Markdown catalogue parsing
# --------------------------------------------------------------------------


def parse_blocks(path: Path) -> dict[str, dict[str, str]]:
    """Parse a catalogue file into {ID: {key: value}}.

    Blocks start at a `## ID` heading; every following `key: value` line becomes
    a field. Anything else is ignored, so prose in the file is free.
    """
    out: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = {}
            continue
        if current and ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            key = key.strip()
            if re.fullmatch(r"[a-z0-9_]+", key):
                out[current][key] = value.strip()
    return out


def as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def money(cents: int) -> str:
    return f"€{cents / 100:,.2f}"


def money_spoken(cents: int) -> str:
    """A price a text-to-speech surface can read without mangling it.

    "€39.95" read literally becomes "euro thirty nine point nine five"; voice
    surfaces get "39 euro 95" instead.
    """
    euros, rest = divmod(abs(int(cents)), 100)
    return f"{euros} euro" if rest == 0 else f"{euros} euro {rest:02d}"


TARIFFS = parse_blocks(CATALOGUE / "tariffs.md")
DEVICES = parse_blocks(CATALOGUE / "devices.md")
CONSENTS = parse_blocks(CATALOGUE / "consents.md")

for _id, _d in DEVICES.items():
    mapping: dict[str, int] = {}
    for pair in _d.get("monthly_by_tariff", "").split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            mapping[k.strip()] = as_int(v)
    _d["_monthly_map"] = mapping  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Cart state (in memory — this is a demo, not a system of record)
# --------------------------------------------------------------------------


@dataclass
class Cart:
    cart_id: str
    tariff_id: str | None = None
    device_id: str | None = None
    customer: dict[str, str] = field(default_factory=dict)
    payment_token: str | None = None
    card_last4: str | None = None
    consents: list[str] = field(default_factory=list)
    order_id: str | None = None
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def tariff(self) -> dict[str, str] | None:
        return TARIFFS.get(self.tariff_id) if self.tariff_id else None

    def device(self) -> dict[str, str] | None:
        return DEVICES.get(self.device_id) if self.device_id else None

    def device_monthly(self) -> int:
        d = self.device()
        if not d or not self.tariff_id:
            return 0
        return d["_monthly_map"].get(self.tariff_id, 0)  # type: ignore[union-attr]

    def totals(self) -> dict[str, int]:
        t = self.tariff()
        d = self.device()
        monthly = as_int(t.get("monthly_initial")) if t else 0
        monthly_after = as_int(t.get("monthly_after_24")) if t else 0
        dev_monthly = self.device_monthly()
        one_off = (as_int(t.get("one_off")) if t else 0) + (as_int(d.get("one_off")) if d else 0)
        return {
            "monthly": monthly + dev_monthly,
            "monthly_after_24": monthly_after + dev_monthly,
            "one_off": one_off,
            "tariff_monthly": monthly,
            "device_monthly": dev_monthly,
        }

    def required_consents(self) -> list[str]:
        t = self.tariff()
        line_type = t.get("line_type", "mobile") if t else "mobile"
        out = []
        for cid, c in CONSENTS.items():
            applies = [a.strip() for a in c.get("applies_to", "all").split(",")]
            if "all" in applies or line_type in applies:
                out.append(cid)
        return out

    def blockers(self) -> list[str]:
        problems = []
        if not self.tariff_id:
            problems.append("No tariff selected. Call search_tariffs, then create_cart.")
        for f, label in (("name", "full name"), ("dob", "date of birth"),
                         ("address", "delivery address"), ("phone", "phone number")):
            if not self.customer.get(f):
                problems.append(f"Missing {label}. Call update_cart with customer details.")
        if not self.payment_token:
            problems.append("No payment method tokenised. Call get_payment_methods.")
        missing = [c for c in self.required_consents()
                   if CONSENTS[c].get("mandatory") == "true" and c not in self.consents]
        for c in missing:
            problems.append(f"Consent not granted: {CONSENTS[c].get('label', c)}")
        return problems

    def public(self) -> dict[str, Any]:
        t, d = self.tariff(), self.device()
        tot = self.totals()
        return {
            "cart_id": self.cart_id,
            "tariff": {"id": self.tariff_id, "name": t.get("name"), "line_type": t.get("line_type"),
                       "monthly": tot["tariff_monthly"]} if t else None,
            "device": {"id": self.device_id, "name": d.get("name"), "brand": d.get("brand"),
                       "storage": d.get("storage"), "colour": d.get("colour"),
                       "monthly": tot["device_monthly"], "one_off": as_int(d.get("one_off"))} if d else None,
            "customer": self.customer,
            "payment": {"token": self.payment_token, "last4": self.card_last4} if self.payment_token else None,
            "consents_granted": self.consents,
            "totals": tot,
            "magenta_eins_discount": as_int(t.get("magenta_eins_discount")) if t else 0,
            "blockers": self.blockers(),
            "order_id": self.order_id,
        }


CARTS: dict[str, Cart] = {}


def get_cart(cart_id: str) -> Cart:
    if cart_id not in CARTS:
        raise ValueError(f"Unknown cart_id {cart_id!r}. Call create_cart first.")
    return CARTS[cart_id]


# --------------------------------------------------------------------------
# Widget scaffolding
# --------------------------------------------------------------------------

CSS = """
:root{--m:#E20074;--mdk:#9D1046;--mbg:#FDF2F8;--ink:#17171A;--grey:#6E6E73;
--faint:#A1A1A8;--line:#E4E4E7;--bg:#F4F4F5;--amber:#B45309;--ambg:#FEF3C7;--green:#15803D}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);
line-height:1.5;font-size:14px;background:transparent;padding:2px}
.card{border:2px solid var(--m);border-radius:13px;overflow:hidden;background:#fff}
.hd{background:var(--m);color:#fff;padding:9px 14px;display:flex;justify-content:space-between;align-items:center}
.hd .t{font-size:13.5px;font-weight:700}
.hd .m{font-size:10.5px;opacity:.9}
.bd{padding:13px}
.ft{padding:9px 14px;border-top:1px solid var(--line);font-size:10.5px;color:var(--faint);background:#FCFCFD}
.opt{border:1.5px solid var(--line);border-radius:10px;padding:11px 13px;margin-bottom:8px;
display:flex;justify-content:space-between;gap:12px;align-items:center;cursor:pointer}
.opt:hover{border-color:var(--m)}
.opt.sel{border-color:var(--m);background:var(--mbg)}
.nm{font-size:14px;font-weight:600}
.sub{font-size:11.5px;color:var(--grey);margin-top:2px}
.pr{font-size:15px;font-weight:700;text-align:right;white-space:nowrap}
.pr small{display:block;font-size:10px;font-weight:500;color:var(--grey)}
.row{display:flex;justify-content:space-between;font-size:13px;padding:5px 0}
.row.tot{border-top:1px solid var(--line);margin-top:6px;padding-top:9px;font-weight:700;font-size:14.5px}
.lbl{color:var(--grey)}
.note{font-size:11.5px;color:var(--grey);background:var(--bg);border-radius:7px;padding:8px 10px;margin-top:9px}
.x{border:1.5px solid var(--m);background:var(--mbg);border-radius:10px;padding:11px 13px;margin-top:10px}
.x .h{font-size:12.5px;font-weight:700;color:var(--mdk);margin-bottom:3px}
.x .b{font-size:12px}
.f{margin-bottom:9px}
.f label{display:block;font-size:11px;font-weight:600;color:var(--grey);margin-bottom:3px}
.f .v{border:1.5px solid var(--line);border-radius:8px;padding:9px 11px;font-size:13.5px;background:#FCFCFD}
.f .v.empty{color:var(--faint);font-style:italic}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.c{display:flex;gap:9px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--line)}
.c:last-child{border-bottom:none}
.box{width:18px;height:18px;border:1.5px solid var(--faint);border-radius:4px;flex:none;margin-top:1px;
display:flex;align-items:center;justify-content:center;font-size:12px;color:#fff}
.box.on{background:var(--m);border-color:var(--m)}
.c .tx{font-size:12px;line-height:1.45}
.c .law{font-size:10px;color:var(--faint);margin-top:2px}
.warn{background:var(--ambg);border:1.5px solid var(--amber);border-radius:9px;padding:10px 12px;
margin-top:9px;font-size:11.5px;color:#5C3A08}
.warn b{color:var(--amber)}
.ok{text-align:center;padding:4px 0}
.ok .tick{width:42px;height:42px;border-radius:50%;background:var(--green);color:#fff;display:flex;
align-items:center;justify-content:center;font-size:21px;margin:0 auto 9px}
.ok .h{font-size:15px;font-weight:700}.ok .s{font-size:12px;color:var(--grey);margin-top:3px}
.st{display:flex;gap:7px;align-items:center;font-size:11.5px;padding:6px 0;
border-top:1px solid var(--line);margin-top:8px}
.st .d{width:7px;height:7px;border-radius:50%;background:var(--green);flex:none}
.qr{text-align:center;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
.qr svg{width:132px;height:132px}
.qr .cap{font-size:11.5px;color:var(--grey);margin-top:6px}
.pill{display:inline-block;font-size:10px;font-weight:600;padding:2px 7px;border-radius:99px;
background:var(--bg);color:var(--grey);margin-left:6px}
.empty-state{font-size:12.5px;color:var(--grey);padding:4px}
"""

# Defensive bridge: MCP Apps hosts deliver the tool result to the iframe. The
# exact surface still differs between hosts, so try the known shapes in turn and
# fall back to the catalogue snapshot embedded at build time.
BRIDGE = """
function paint(d){try{render(d||{})}catch(e){
document.body.innerHTML='<div class="card"><div class="bd empty-state">'+e.message+'</div></div>'}}
function boot(){
  var w=window;
  var direct=(w.mcp&&(w.mcp.toolOutput||w.mcp.toolResult))||(w.openai&&w.openai.toolOutput)||w.__TOOL_OUTPUT__;
  if(direct){paint(direct);return}
  var done=false;
  w.addEventListener('message',function(e){
    if(done||!e.data)return;
    var d=e.data;
    var p=d.toolOutput||d.structuredContent||(d.params&&(d.params.toolOutput||d.params.structuredContent))
        ||(d.result&&(d.result.structuredContent||d.result.toolOutput));
    if(p){done=true;paint(p)}
  });
  try{w.parent.postMessage({jsonrpc:"2.0",id:1,method:"ui/initialize"},'*')}catch(e){}
  setTimeout(function(){if(!done)paint(FALLBACK)},600);
}
if(document.readyState!=='loading')boot();else document.addEventListener('DOMContentLoaded',boot);
"""


def widget(body_js: str, fallback: Any) -> str:
    """Wrap a render() implementation into a complete MCP Apps HTML document."""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>" + CSS + "</style></head><body><div id='root'></div>"
        "<script>const FALLBACK=" + json.dumps(fallback) + ";\n"
        + body_js + "\n" + BRIDGE + "</script></body></html>"
    )


def eur(expr: str) -> str:
    """JS helper name used inside widget scripts."""
    return expr


JS_HELPERS = """
const R=document.getElementById('root');
const E=c=>'€'+(Number(c||0)/100).toFixed(2);
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const shell=(title,meta,body,foot)=>`<div class="card"><div class="hd"><span class="t">${esc(title)}</span>
<span class="m">${esc(meta||'Rendered by Telekom')}</span></div><div class="bd">${body}</div>
${foot?`<div class="ft">${esc(foot)}</div>`:''}</div>`;
"""

apps = Apps()

# ---- tariff picker -------------------------------------------------------

apps.add_html_resource(
    "ui://telekom/tariffs.html",
    widget(
        JS_HELPERS + """
function render(d){
  const list=(d.tariffs&&d.tariffs.length)?d.tariffs:FALLBACK.tariffs;
  const rows=list.map(t=>`<div class="opt"><div><div class="nm">${esc(t.name)}</div>
  <div class="sub">${esc(t.headline)} · ${esc(t.speed)}</div></div>
  <div class="pr">${E(t.monthly_initial)}<small>per month</small></div></div>`).join('');
  R.innerHTML=shell(d.title||'Telekom tariffs','Rendered by Telekom',
    rows||'<div class="empty-state">No tariffs matched.</div>',
    'Minimum term applies · Prices include VAT · Price changes after the minimum term');
}""",
        {"tariffs": [{"name": t.get("name"), "headline": t.get("headline"), "speed": t.get("speed"),
                      "monthly_initial": as_int(t.get("monthly_initial"))} for t in TARIFFS.values()]},
    ),
    title="Telekom tariff picker",
    csp=ResourceCsp(resource_domains=["https://www.telekom.de"]),
    prefers_border=False,
)

# ---- tariff detail -------------------------------------------------------

apps.add_html_resource(
    "ui://telekom/tariff-detail.html",
    widget(
        JS_HELPERS + """
function render(d){
  const t=d.tariff||FALLBACK.tariff;if(!t){R.innerHTML='';return}
  const b=`<div class="row"><span class="lbl">Monthly, months 1–${esc(t.term_months)}</span><span>${E(t.monthly_initial)}</span></div>
  <div class="row"><span class="lbl">Monthly, from month ${Number(t.term_months)+1}</span><span>${E(t.monthly_after_24)}</span></div>
  <div class="row"><span class="lbl">One-off charge</span><span>${E(t.one_off)}</span></div>
  <div class="row"><span class="lbl">Minimum term</span><span>${esc(t.term_months)} months</span></div>
  <div class="row"><span class="lbl">Speed</span><span>${esc(t.speed)}</span></div>
  <div class="note"><b>Included.</b> ${esc(t.extras)}<br><b>Roaming.</b> ${esc(t.roaming)}</div>
  ${Number(t.magenta_eins_discount)>0?`<div class="x"><div class="h">MagentaEINS eligible</div>
  <div class="b">Combining this with a Telekom fixed line reduces the monthly price by ${E(t.magenta_eins_discount)}.</div></div>`:''}`;
  R.innerHTML=shell(t.name+' — price detail','Rendered by Telekom',b,
    'Full price information per TKG section 54 is in the Produktinformationsblatt');
}""",
        {"tariff": None},
    ),
    title="Tariff detail",
    prefers_border=False,
)

# ---- device picker -------------------------------------------------------

apps.add_html_resource(
    "ui://telekom/devices.html",
    widget(
        JS_HELPERS + """
function render(d){
  const list=(d.devices&&d.devices.length)?d.devices:FALLBACK.devices;
  const rows=list.map(x=>`<div class="opt"><div><div class="nm">${esc(x.name)} · ${esc(x.storage)}
  ${x.stock==='backorder'?'<span class="pill">backorder</span>':''}</div>
  <div class="sub">${esc(x.colour)} · ${esc(x.brand)}${x.one_off?' · '+E(x.one_off)+' upfront':''}</div></div>
  <div class="pr">${x.monthly?'+'+E(x.monthly):E(0)}<small>per month</small></div></div>`).join('');
  R.innerHTML=shell(d.title||'Devices','Rendered by Telekom',
    rows||'<div class="empty-state">No devices available on this tariff.</div>',
    'Device price depends on the selected tariff · Images served from the Telekom CDN declared in this widget CSP');
}""",
        {"devices": [{"name": d.get("name"), "storage": d.get("storage"), "colour": d.get("colour"),
                      "brand": d.get("brand"), "stock": d.get("stock"),
                      "one_off": as_int(d.get("one_off")), "monthly": 0} for d in DEVICES.values()]},
    ),
    title="Device picker",
    csp=ResourceCsp(resource_domains=["https://www.telekom.de"]),
    prefers_border=False,
)

# ---- device detail -------------------------------------------------------

apps.add_html_resource(
    "ui://telekom/device-detail.html",
    widget(
        JS_HELPERS + """
function render(d){
  const x=d.device||FALLBACK.device;if(!x){R.innerHTML='';return}
  const rows=(x.pricing||[]).map(p=>`<div class="row"><span class="lbl">On ${esc(p.tariff)}</span>
  <span>${p.monthly?'+'+E(p.monthly)+' / mo':'included'}</span></div>`).join('');
  R.innerHTML=shell(x.name+' · '+x.storage,'Rendered by Telekom',
    `<div class="note">${esc(x.highlights)}</div>
     <div class="row"><span class="lbl">Colour</span><span>${esc(x.colour)}</span></div>
     <div class="row"><span class="lbl">Availability</span><span>${esc(x.stock)}</span></div>
     <div class="row"><span class="lbl">Upfront</span><span>${E(x.one_off)}</span></div>${rows}`,
    'Monthly instalment varies by tariff — the same handset is priced differently on each');
}""",
        {"device": None},
    ),
    title="Device detail",
    prefers_border=False,
)

# ---- cart ----------------------------------------------------------------

CART_JS = JS_HELPERS + """
function render(d){
  const c=d.cart||FALLBACK.cart;if(!c){R.innerHTML='';return}
  const t=c.tariff,x=c.device,tot=c.totals||{};
  let b='';
  if(t)b+=`<div class="row"><span class="lbl">${esc(t.name)}</span><span>${E(t.monthly)} / mo</span></div>`;
  if(x&&x.name!=='No device')b+=`<div class="row"><span class="lbl">${esc(x.name)} ${esc(x.storage||'')}</span><span>${E(x.monthly)} / mo</span></div>`;
  if(tot.one_off)b+=`<div class="row"><span class="lbl">One-off charges</span><span>${E(tot.one_off)}</span></div>`;
  b+=`<div class="row tot"><span>Monthly total</span><span>${E(tot.monthly)}</span></div>`;
  if(c.magenta_eins_discount>0)b+=`<div class="x"><div class="h">You qualify for MagentaEINS</div>
  <div class="b">Adding a Telekom fixed line at your address reduces this by ${E(c.magenta_eins_discount)} per month, for as long as both contracts run.</div></div>`;
  if(tot.monthly_after_24&&tot.monthly_after_24!==tot.monthly)
    b+=`<div class="note">From month 25 the monthly total becomes ${E(tot.monthly_after_24)}.</div>`;
  const cu=c.customer||{};
  const fld=(l,v)=>`<div class="f"><label>${l}</label><div class="v ${v?'':'empty'}">${v?esc(v):'not provided yet'}</div></div>`;
  if(Object.keys(cu).length||d.show_customer)
    b+=`<div style="margin-top:12px">${fld('Full name',cu.name)}
    <div class="g2">${fld('Date of birth',cu.dob)}${fld('Phone',cu.phone)}</div>
    ${fld('Delivery address',cu.address)}</div>`;
  if(c.blockers&&c.blockers.length)
    b+=`<div class="warn"><b>Still needed before this order can be placed.</b><br>${c.blockers.map(esc).join('<br>')}</div>`;
  R.innerHTML=shell('Your cart','Rendered by Telekom',b,
    'Cart valid for 30 minutes · Prices recalculated server-side on every change');
}"""

apps.add_html_resource("ui://telekom/cart.html", widget(CART_JS, {"cart": None}),
                       title="Cart summary", prefers_border=False)

# ---- payment -------------------------------------------------------------

apps.add_html_resource(
    "ui://telekom/payment.html",
    widget(
        JS_HELPERS + """
function render(d){
  const m=(d.methods&&d.methods.length)?d.methods:FALLBACK.methods;
  const rows=m.map(x=>`<div class="opt ${x.selected?'sel':''}"><div><div class="nm">${esc(x.label)}</div>
  <div class="sub">${esc(x.detail)}</div></div><div class="pr" style="font-size:12px">${esc(x.status||'')}</div></div>`).join('');
  const tok=d.token?`<div class="note"><b>Token issued.</b> ${esc(d.token)} — scoped to this cart and this merchant,
  single use, expires ${esc(d.expires||'in 15 minutes')}. The agent never receives the card number.</div>`:'';
  R.innerHTML=shell('Payment method','Telekom checkout · embedded',
    rows+tok+`<div class="warn"><b>Cards only, by design.</b> Card credentials can be tokenised and delegated
    under the AP2 payment-mandate model, so the agent can carry an authorisation without ever seeing the PAN.
    SEPA direct debit cannot: a mandate must be granted to the creditor directly, which is why it is absent here.</div>`,
    'PSD2 strong customer authentication may be requested by the issuing bank');
}""",
        {"methods": [{"label": "Card", "detail": "Visa · Mastercard · Amex", "status": "available", "selected": True}]},
    ),
    title="Payment method",
    prefers_border=False,
)

# ---- consents ------------------------------------------------------------

apps.add_html_resource(
    "ui://telekom/consents.html",
    widget(
        JS_HELPERS + """
function render(d){
  const list=(d.consents&&d.consents.length)?d.consents:FALLBACK.consents;
  const rows=list.map(c=>`<div class="c"><div class="box ${c.granted?'on':''}">${c.granted?'✓':''}</div>
  <div class="tx"><b>${esc(c.label)}</b>${c.mandatory?'':' <span class="pill">optional</span>'}<br>${esc(c.body)}
  <div class="law">${esc(c.statute)}</div></div></div>`).join('');
  const t=d.totals||{};
  R.innerHTML=shell('Before you order','Telekom checkout · embedded',
    rows+(t.monthly?`<div class="row tot" style="margin-top:12px"><span>${E(t.monthly)} / month</span>
    <span>+ ${E(t.one_off)} once</span></div>
    <div class="note" style="text-align:center">The order button is labelled “Zahlungspflichtig bestellen”,
    the wording required by BGB section 312j</div>`:''),
    'Each consent is timestamped and stored against the order record');
}""",
        {"consents": [{"label": c.get("label"), "body": c.get("body"), "statute": c.get("statute"),
                       "mandatory": c.get("mandatory") == "true", "granted": False}
                      for c in CONSENTS.values()]},
    ),
    title="Required consents",
    prefers_border=False,
)

# ---- order confirmation --------------------------------------------------

apps.add_html_resource(
    "ui://telekom/order.html",
    widget(
        JS_HELPERS + """
function render(d){
  const o=d.order||FALLBACK.order;if(!o){R.innerHTML='';return}
  const st=(o.status_lines||[]).map(s=>`<div class="st"><span class="d" style="background:${s.pending?'#B45309':'#15803D'}"></span><span>${esc(s.text)}</span></div>`).join('');
  R.innerHTML=shell('Order '+o.order_id,'Rendered by Telekom',
    `<div class="ok"><div class="tick">✓</div><div class="h">${esc(o.summary)}</div>
     <div class="s">${E(o.monthly)} per month · ${E(o.one_off)} one-off · ${esc(o.term)}</div></div>
     ${st}<div class="note">Your withdrawal period runs for 14 days from delivery. Confirmation and all
     contract documents have been sent to you.</div>
     <div class="qr">${o.qr||''}<div class="cap">Scan to install MeinMagenta and track this order</div></div>`,
    'Order status stays queryable through the assistant');
}""",
        {"order": None},
    ),
    title="Order confirmation",
    prefers_border=False,
)


# --------------------------------------------------------------------------
# Display layer
# --------------------------------------------------------------------------
#
# Almost no client can render the MCP Apps widget today: the extension is only
# advertised on wire revisions the `initialize` handshake cannot reach, so
# `client_supports_apps()` is False nearly everywhere. SEP-2133 requires a
# UI-bound tool to degrade gracefully, so every tool also returns
# `display_markdown` — Telekom's own rendering of the same figures — and tells
# the model to print that verbatim instead of paraphrasing prices.

WIDGET_HTML: dict[str, str] = {str(b.resource.uri): b.resource.text for b in apps.resources()}


def live_widget(uri: str, data: Any) -> str:
    """Re-render a registered widget document with this call's data baked in.

    The registered copy carries a build-time catalogue snapshot as `FALLBACK`;
    swapping that for the live payload makes the document correct standalone, so
    it renders in clients that never deliver tool output into the iframe.
    """
    head, marker, rest = WIDGET_HTML[uri].partition("const FALLBACK=")
    _snapshot, terminator, tail = rest.partition(";\n")
    return head + marker + json.dumps(data) + terminator + tail


PRICE_RULES = ("Prices are euro cents and authoritative exactly as returned. Never sum components, "
               "apply a discount, or round them yourself.")


def respond(ctx: Context, payload: dict[str, Any], *, uri: str, markdown: str,
            widget_data: Any) -> dict[str, Any] | CallToolResult:
    """Attach the display contract, plus the widget itself where it can render."""
    payload = dict(payload)
    payload["display_markdown"] = markdown
    payload["display_note"] = (
        "The widget already shows this. Do not restate prices in prose."
        if client_supports_apps(ctx) else
        "No widget is on screen in this client. Show the customer display_markdown "
        "verbatim — it is Telekom's own rendering. " + PRICE_RULES
    )
    if not MCP_UI_ENABLED:
        return payload
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload, ensure_ascii=False)),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=uri, mime_type="text/html", text=live_widget(uri, widget_data),
                ),
            ),
        ],
        structured_content=payload,
    )


FOOTER_TARIFF = "_Minimum term applies · prices incl. VAT · price changes after the minimum term._"


def md_tariff_rows(rows: list[dict[str, Any]], title: str) -> str:
    if not rows:
        return f"**{title}**\n\nNo tariffs matched those filters."
    out = [f"**{title}**", "", "| Tariff | Data | Per month | After 24 months |", "|---|---|---|---|"]
    for t in rows:
        gb = t.get("data_gb") or 0
        data = ("Unlimited" if t.get("line_type") == "mobile" else "—") if gb == 0 else f"{gb} GB"
        out.append(f"| {t['name']} | {data} | {money(t['monthly_initial'])} "
                   f"| {money(t['monthly_after_24'])} |")
    return "\n".join(out + ["", FOOTER_TARIFF])


def md_tariff_detail(t: dict[str, Any]) -> str:
    term = t["term_months"]
    out = [f"**{t['name']}**", "",
           f"| | |", "|---|---|",
           f"| Months 1–{term} | {money(t['monthly_initial'])} per month |",
           f"| From month {term + 1} | {money(t['monthly_after_24'])} per month |",
           f"| One-off charge | {money(t['one_off'])} |",
           f"| Minimum term | {term} months |",
           f"| Speed | {t.get('speed', '—')} |",
           "", f"Included: {t.get('extras', '—')}", "", f"Roaming: {t.get('roaming', '—')}"]
    if t.get("magenta_eins_discount"):
        out += ["", f"MagentaEINS: adding a Telekom fixed line reduces this by "
                    f"{money(t['magenta_eins_discount'])} per month."]
    return "\n".join(out + ["", FOOTER_TARIFF])


def md_devices(rows: list[dict[str, Any]], title: str) -> str:
    if not rows:
        return f"**{title}**\n\nNo devices are available on this tariff."
    out = [f"**{title}**", "", "| Device | Storage | Upfront | Per month |", "|---|---|---|---|"]
    for d in rows:
        flag = " _(backorder)_" if d.get("stock") == "backorder" else ""
        monthly = f"+{money(d['monthly'])}" if d.get("monthly") else "included"
        out.append(f"| {d['name']}{flag} | {d.get('storage', '—')} | {money(d.get('one_off', 0))} | {monthly} |")
    return "\n".join(out + ["", "_Device instalment depends on the selected tariff._"])


def md_device_detail(d: dict[str, Any]) -> str:
    out = [f"**{d['name']} · {d.get('storage', '')}**".rstrip(), "",
           f"{d.get('highlights', '')}", "",
           "| | |", "|---|---|",
           f"| Colour | {d.get('colour', '—')} |",
           f"| Availability | {d.get('stock', '—')} |",
           f"| Upfront | {money(d.get('one_off', 0))} |"]
    for p in d.get("pricing", []):
        monthly = f"+{money(p['monthly'])} / mo" if p.get("monthly") else "included"
        out.append(f"| On {p['tariff']} | {monthly} |")
    return "\n".join(out + ["", "_The same handset is priced differently on each tariff._"])


def md_cart(cart: dict[str, Any]) -> str:
    tot = cart.get("totals", {})
    out = ["**Your cart**", "", "| Item | Per month |", "|---|---|"]
    if cart.get("tariff"):
        out.append(f"| {cart['tariff']['name']} | {money(cart['tariff']['monthly'])} |")
    dev = cart.get("device")
    if dev and dev.get("name") != "No device":
        out.append(f"| {dev['name']} {dev.get('storage') or ''} | {money(dev['monthly'])} |".replace("  ", " "))
    out.append(f"| **Monthly total** | **{money(tot.get('monthly', 0))}** |")
    if tot.get("one_off"):
        out.append(f"| One-off charges | {money(tot['one_off'])} |")
    after = tot.get("monthly_after_24")
    if after and after != tot.get("monthly"):
        out += ["", f"From month 25 the monthly total becomes {money(after)}."]
    if cart.get("magenta_eins_discount"):
        out += ["", f"You qualify for MagentaEINS: adding a Telekom fixed line at your address "
                    f"reduces this by {money(cart['magenta_eins_discount'])} per month."]
    if cart.get("blockers"):
        out += ["", "**Still needed before this order can be placed**"] + [f"- {b}" for b in cart["blockers"]]
    return "\n".join(out)


def md_payment(methods: list[dict[str, Any]], totals: dict[str, int], token: str | None) -> str:
    out = ["**Payment method**", "", "| Method | Status |", "|---|---|"]
    for m in methods:
        out.append(f"| {m['label']} — {m['detail']} | {m.get('status', '')} |")
    out += ["", f"Amount due: {money(totals.get('monthly', 0))} per month "
                f"plus {money(totals.get('one_off', 0))} once."]
    if token:
        out += ["", f"Token `{token}` issued — scoped to this cart and merchant, single use. "
                    "The agent never receives the card number."]
    out += ["", "_SEPA Lastschrift is deliberately unavailable: a direct debit mandate is granted to "
                "the creditor and cannot be delegated through an agent._"]
    return "\n".join(out)


def md_consents(items: list[dict[str, Any]], totals: dict[str, int]) -> str:
    out = ["**Before you order**", ""]
    for c in items:
        box = "[x]" if c["granted"] else "[ ]"
        tag = "" if c["mandatory"] else " _(optional)_"
        out += [f"- {box} **{c['label']}**{tag} — {c['body']} ({c['statute']})"]
    out += ["", f"Total: {money(totals.get('monthly', 0))} per month plus "
                f"{money(totals.get('one_off', 0))} once.", "",
            '_The order button is labelled "Zahlungspflichtig bestellen", the wording required by BGB §312j._']
    return "\n".join(out)


def md_order(order: dict[str, Any]) -> str:
    out = [f"**Order {order['order_id']} confirmed**", "", order["summary"], "",
           f"{money(order['monthly'])} per month · {money(order['one_off'])} one-off · {order['term']}", ""]
    for line in order.get("status_lines", []):
        out.append(f"- {'⏳' if line.get('pending') else '✅'} {line['text']}")
    out += ["", "Your withdrawal period runs for 14 days from delivery. Confirmation and all contract "
                "documents have been sent to you.",
            "", "Scan the QR code in the order widget to install MeinMagenta and track this order."]
    return "\n".join(out)


# ---- tools ---------------------------------------------------------------

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)


@apps.tool(
    resource_uri="ui://telekom/tariffs.html",
    name="search_tariffs",
    title="Search tariffs",
    description=("Find Telekom tariffs. line_type is 'mobile', 'fixed' or 'ott'. min_data_gb filters "
                 "mobile tariffs by allowance; max_monthly filters by monthly price in euro cents. "
                 "Leave a filter empty when the customer has not stated it — do not guess. "
                 "Show the customer display_markdown as returned; never quote a monthly price that "
                 "is not in it."),
    annotations=READ,
)
def search_tariffs(ctx: Context, line_type: str = "", min_data_gb: int = 0, max_monthly: int = 0,
                   user_query: str = "") -> dict[str, Any]:
    """Search the tariff catalogue.

    Args:
        line_type: One of 'mobile', 'fixed', 'ott'. Empty returns all.
        min_data_gb: Minimum mobile data allowance in GB. 0 means no filter.
        max_monthly: Maximum initial monthly price in euro cents. 0 means no filter.
        user_query: The customer's own words, passed through for ranking.
    """
    out = []
    for tid, t in TARIFFS.items():
        if line_type and t.get("line_type") != line_type:
            continue
        data = as_int(t.get("data_gb"))
        if min_data_gb and t.get("line_type") == "mobile" and data != 0 and data < min_data_gb:
            continue
        if max_monthly and as_int(t.get("monthly_initial")) > max_monthly:
            continue
        out.append({
            "id": tid, "name": t.get("name"), "line_type": t.get("line_type"),
            "headline": t.get("headline"), "speed": t.get("speed"),
            "data_gb": data, "monthly_initial": as_int(t.get("monthly_initial")),
            "monthly_after_24": as_int(t.get("monthly_after_24")),
            "monthly_spoken": money_spoken(as_int(t.get("monthly_initial"))),
            "term_months": as_int(t.get("term_months")),
        })
    out.sort(key=lambda x: x["monthly_initial"])
    label = {"mobile": "Mobile tariffs", "fixed": "Home internet", "ott": "TV and streaming"}.get(line_type, "Telekom tariffs")
    payload = {
        "title": label,
        "tariffs": out,
        "currency": "eur",
        "next_step": "Call get_tariff_details for the one the customer is interested in.",
    }
    return respond(ctx, payload, uri="ui://telekom/tariffs.html",
                   markdown=md_tariff_rows(out, label), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/tariff-detail.html",
    name="get_tariff_details",
    title="Tariff detail",
    description="Full price breakdown for one tariff, including what changes after the minimum term.",
    annotations=READ,
)
def get_tariff_details(ctx: Context, tariff_id: str) -> dict[str, Any]:
    """Get the full detail of a single tariff.

    Args:
        tariff_id: A tariff ID from search_tariffs, for example MM_M.
    """
    t = TARIFFS.get(tariff_id)
    if not t:
        return {"error": f"Unknown tariff_id {tariff_id!r}", "valid_ids": list(TARIFFS)}
    tariff = {
        "id": tariff_id, "name": t.get("name"), "line_type": t.get("line_type"),
        "speed": t.get("speed"), "extras": t.get("extras"), "roaming": t.get("roaming"),
        "monthly_initial": as_int(t.get("monthly_initial")),
        "monthly_after_24": as_int(t.get("monthly_after_24")),
        "monthly_spoken": money_spoken(as_int(t.get("monthly_initial"))),
        "one_off": as_int(t.get("one_off")), "term_months": as_int(t.get("term_months")),
        "magenta_eins_discount": as_int(t.get("magenta_eins_discount")),
        "device_eligible": t.get("device_eligible") == "true",
    }
    payload = {
        "tariff": tariff,
        "next_step": ("Call search_devices with this tariff_id." if t.get("device_eligible") == "true"
                      else "This tariff has no device option. Call create_cart."),
    }
    return respond(ctx, payload, uri="ui://telekom/tariff-detail.html",
                   markdown=md_tariff_detail(tariff), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/devices.html",
    name="search_devices",
    title="Search devices",
    description=("Devices available on a given tariff, priced for that tariff. Only mobile tariffs "
                 "support devices. The same handset costs a different monthly instalment on each "
                 "tariff, so never quote a device price without the tariff it belongs to."),
    annotations=READ,
)
def search_devices(ctx: Context, tariff_id: str, brand: str = "", in_stock_only: bool = False) -> dict[str, Any]:
    """List devices available on a tariff.

    Args:
        tariff_id: The tariff the device will be combined with.
        brand: Optional brand filter, for example Apple or Samsung.
        in_stock_only: Exclude backordered devices.
    """
    t = TARIFFS.get(tariff_id)
    if not t:
        return {"error": f"Unknown tariff_id {tariff_id!r}", "valid_ids": list(TARIFFS)}
    if t.get("device_eligible") != "true":
        return {"devices": [], "note": f"{t.get('name')} is not sold with a device.",
                "next_step": "Call create_cart with this tariff only."}
    out = []
    for did, d in DEVICES.items():
        monthly = d["_monthly_map"].get(tariff_id)  # type: ignore[union-attr]
        if monthly is None:
            continue
        if brand and brand.lower() not in d.get("brand", "").lower():
            continue
        if in_stock_only and d.get("stock") != "in_stock":
            continue
        out.append({"id": did, "name": d.get("name"), "brand": d.get("brand"),
                    "storage": d.get("storage"), "colour": d.get("colour"),
                    "stock": d.get("stock"), "one_off": as_int(d.get("one_off")),
                    "monthly": monthly, "monthly_spoken": money_spoken(monthly)})
    out.sort(key=lambda x: x["monthly"])
    title = f"Devices on {t.get('name')}"
    payload = {
        "title": title,
        "tariff_id": tariff_id, "devices": out, "currency": "eur",
        "next_step": "Call create_cart with tariff_id and device_id.",
    }
    return respond(ctx, payload, uri="ui://telekom/devices.html",
                   markdown=md_devices(out, title), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/device-detail.html",
    name="get_device_details",
    title="Device detail",
    description="Full detail for one device, including how its instalment changes across tariffs.",
    annotations=READ,
)
def get_device_details(ctx: Context, device_id: str) -> dict[str, Any]:
    """Get the full detail of a single device.

    Args:
        device_id: A device ID from search_devices, for example IP17P_256.
    """
    d = DEVICES.get(device_id)
    if not d:
        return {"error": f"Unknown device_id {device_id!r}", "valid_ids": list(DEVICES)}
    pricing = [{"tariff": TARIFFS[t].get("name"), "tariff_id": t, "monthly": m}
               for t, m in d["_monthly_map"].items() if t in TARIFFS]  # type: ignore[union-attr]
    device = {"id": device_id, "name": d.get("name"), "brand": d.get("brand"),
              "storage": d.get("storage"), "colour": d.get("colour"),
              "stock": d.get("stock"), "one_off": as_int(d.get("one_off")),
              "highlights": d.get("highlights"), "pricing": pricing}
    payload = {
        "device": device,
        "next_step": "Call create_cart with the chosen tariff_id and this device_id.",
    }
    return respond(ctx, payload, uri="ui://telekom/device-detail.html",
                   markdown=md_device_detail(device), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/cart.html",
    name="create_cart",
    title="Create cart",
    description=("Create a server-side cart. Returns a cart_id; the agent holds only that ID and "
                 "prices are recomputed here on every read. magenta_eins_discount is a conditional "
                 "saving, not an applied one — describe it as available with a Telekom fixed line, "
                 "never as already deducted from the totals."),
    annotations=WRITE,
)
def create_cart(ctx: Context, tariff_id: str, device_id: str = "") -> dict[str, Any]:
    """Create a new cart.

    Args:
        tariff_id: The selected tariff.
        device_id: Optional device to combine with it.
    """
    if tariff_id not in TARIFFS:
        return {"error": f"Unknown tariff_id {tariff_id!r}", "valid_ids": list(TARIFFS)}
    if device_id and device_id not in DEVICES:
        return {"error": f"Unknown device_id {device_id!r}", "valid_ids": list(DEVICES)}
    if device_id and tariff_id not in DEVICES[device_id]["_monthly_map"]:  # type: ignore[operator]
        return {"error": f"{DEVICES[device_id].get('name')} cannot be combined with {TARIFFS[tariff_id].get('name')}."}
    cart = Cart(cart_id="crt_" + uuid.uuid4().hex[:8], tariff_id=tariff_id, device_id=device_id or None)
    CARTS[cart.cart_id] = cart
    pub = cart.public()
    payload = {
        "cart": pub, "show_customer": True,
        "monthly_total_spoken": money_spoken(pub["totals"]["monthly"]),
        "suggested_additions": ([{"type": "bundle_discount", "product": "MagentaEINS",
                                  "saves_monthly": pub["magenta_eins_discount"],
                                  "condition": "add_fixed_line_same_address"}]
                                if pub["magenta_eins_discount"] else []),
        "next_step": ("Call update_cart with the customer's name, date of birth, delivery address "
                      "and phone number. Ask for them conversationally, one or two at a time."),
    }
    return respond(ctx, payload, uri="ui://telekom/cart.html",
                   markdown=md_cart(pub), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/cart.html",
    name="update_cart",
    title="Update cart",
    description=("Change the tariff or device on a cart, or record the customer's checkout details: "
                 "full name, date of birth (YYYY-MM-DD), delivery address and phone number."),
    annotations=WRITE,
)
def update_cart(ctx: Context, cart_id: str, tariff_id: str = "", device_id: str = "", name: str = "",
                dob: str = "", address: str = "", phone: str = "") -> dict[str, Any]:
    """Update a cart's contents or the customer's checkout details.

    Args:
        cart_id: The cart to update.
        tariff_id: Replace the tariff.
        device_id: Replace the device. Pass SIMONLY to remove the handset.
        name: Customer's full name.
        dob: Date of birth in YYYY-MM-DD form.
        address: Full delivery address including postcode and city.
        phone: Contact phone number.
    """
    try:
        cart = get_cart(cart_id)
    except ValueError as exc:
        return {"error": str(exc)}
    if tariff_id:
        if tariff_id not in TARIFFS:
            return {"error": f"Unknown tariff_id {tariff_id!r}"}
        cart.tariff_id = tariff_id
    if device_id:
        if device_id not in DEVICES:
            return {"error": f"Unknown device_id {device_id!r}"}
        cart.device_id = device_id
    if dob and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob.strip()):
        return {"error": "dob must be in YYYY-MM-DD form.", "cart": cart.public()}
    if dob:
        try:
            born = datetime.strptime(dob.strip(), "%Y-%m-%d")
        except ValueError:
            return {"error": "dob is not a real date.", "cart": cart.public()}
        age = (datetime.now() - born).days / 365.25
        if age < 18:
            return {"error": "Customer must be at least 18 to conclude a contract.",
                    "cart": cart.public()}
    for key, value in (("name", name), ("dob", dob), ("address", address), ("phone", phone)):
        if value:
            cart.customer[key] = value.strip()
    pub = cart.public()
    payload = {"cart": pub, "show_customer": True,
               "monthly_total_spoken": money_spoken(pub["totals"]["monthly"]),
               "next_step": ("Call get_payment_methods." if not cart.blockers()
                             else "Resolve the blockers listed on the cart, then call get_payment_methods.")}
    return respond(ctx, payload, uri="ui://telekom/cart.html",
                   markdown=md_cart(pub), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/payment.html",
    name="get_payment_methods",
    title="Payment methods",
    description=("Show available payment methods and tokenise the customer's card. Cards only: a card "
                 "credential can be delegated to an agent as a scoped token under the AP2 mandate model, "
                 "whereas a SEPA mandate must be granted to the creditor directly."),
    annotations=WRITE,
)
def get_payment_methods(ctx: Context, cart_id: str, tokenise: bool = False, card_last4: str = "") -> dict[str, Any]:
    """List payment methods, and optionally issue a scoped payment token.

    Args:
        cart_id: The cart being paid for.
        tokenise: Set true once the customer has agreed to pay by card.
        card_last4: Last four digits only, for display. Never send a full card number.
    """
    try:
        cart = get_cart(cart_id)
    except ValueError as exc:
        return {"error": str(exc)}
    if len(card_last4) > 4 or (card_last4 and not card_last4.isdigit()):
        return {"error": "card_last4 must be at most four digits. Never send a full card number to this tool."}
    methods = [{"label": "Card", "detail": "Visa · Mastercard · Amex", "status": "available", "selected": True},
               {"label": "SEPA Lastschrift", "detail": "Not available in an agent session",
                "status": "unsupported", "selected": False}]
    result: dict[str, Any] = {"cart_id": cart_id, "methods": methods,
                              "totals": cart.totals(),
                              "note": ("SEPA is deliberately unavailable here. A direct debit mandate is an "
                                       "authorisation to the creditor and cannot be delegated through an agent.")}
    if tokenise:
        cart.payment_token = "spt_" + uuid.uuid4().hex[:12]
        cart.card_last4 = card_last4 or "4417"
        result["token"] = cart.payment_token
        result["expires"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime("%H:%M UTC")
        result["token_scope"] = {"merchant": "telekom_de", "cart_id": cart_id,
                                 "max_amount": cart.totals()["monthly"] + cart.totals()["one_off"],
                                 "currency": "eur", "reason": "recurring_and_one_off"}
        result["next_step"] = "Call get_required_consents."
    else:
        result["next_step"] = ("Ask the customer to confirm payment by card and for the last four digits, "
                               "then call this tool again with tokenise=true.")
    return respond(ctx, result, uri="ui://telekom/payment.html",
                   markdown=md_payment(methods, cart.totals(), result.get("token")),
                   widget_data=result)


@apps.tool(
    resource_uri="ui://telekom/consents.html",
    name="get_required_consents",
    title="Required consents",
    description=("List the consents this order requires, and record the ones the customer grants. "
                 "Present them individually and let the customer respond; never grant them on the "
                 "customer's behalf or in a single batch without asking."),
    annotations=WRITE,
)
def get_required_consents(ctx: Context, cart_id: str, grant: list[str] | None = None) -> dict[str, Any]:
    """Fetch and optionally record consents.

    Args:
        cart_id: The cart being ordered.
        grant: Consent IDs the customer has explicitly agreed to in this turn.
    """
    try:
        cart = get_cart(cart_id)
    except ValueError as exc:
        return {"error": str(exc)}
    required = cart.required_consents()
    for cid in (grant or []):
        if cid in required and cid not in cart.consents:
            cart.consents.append(cid)
    items = [{"id": cid, "label": CONSENTS[cid].get("label"), "body": CONSENTS[cid].get("body"),
              "statute": CONSENTS[cid].get("statute"),
              "mandatory": CONSENTS[cid].get("mandatory") == "true",
              "granted": cid in cart.consents} for cid in required]
    outstanding = [i["id"] for i in items if i["mandatory"] and not i["granted"]]
    payload = {
        "cart_id": cart_id, "consents": items, "totals": cart.totals(),
        "outstanding": outstanding,
        "next_step": ("Call complete_order." if not outstanding else
                      "Read the outstanding consents to the customer and call this tool again with "
                      "grant=[...] for the ones they agree to."),
        "order_button_label": "Zahlungspflichtig bestellen",
    }
    return respond(ctx, payload, uri="ui://telekom/consents.html",
                   markdown=md_consents(items, cart.totals()), widget_data=payload)


@apps.tool(
    resource_uri="ui://telekom/order.html",
    name="complete_order",
    title="Place the order",
    description=("Place the order. Fails with a list of blockers unless the cart has a tariff, the "
                 "customer's name, date of birth, address and phone, a tokenised card, and every "
                 "mandatory consent granted."),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
)
def complete_order(ctx: Context, cart_id: str) -> dict[str, Any]:
    """Conclude the contract and return the order confirmation.

    Args:
        cart_id: The cart to convert into an order.
    """
    try:
        cart = get_cart(cart_id)
    except ValueError as exc:
        return {"error": str(exc)}
    blockers = cart.blockers()
    if blockers:
        return {"error": "Order cannot be placed yet.", "blockers": blockers, "cart": cart.public()}
    if not cart.order_id:
        cart.order_id = "AB-" + uuid.uuid4().hex[:4].upper() + "-2027"

    t, d = cart.tariff(), cart.device()
    tot = cart.totals()
    line_type = t.get("line_type", "mobile") if t else "mobile"

    status = [{"text": f"Credit check passed · contract concluded {datetime.now().strftime('%H:%M')} CET"}]
    if line_type == "mobile":
        status.append({"text": "eSIM profile ready — activate it from the MeinMagenta app"})
        if d and d.get("name") != "No device":
            status.append({"text": f"{d.get('name')} dispatched · DHL 00340434", "pending": True})
    elif line_type == "fixed":
        status.append({"text": "Router dispatched · DHL 00340434", "pending": True})
        status.append({"text": "Technician appointment to be confirmed by SMS", "pending": True})
    else:
        status.append({"text": "Service activated — available now in MagentaTV"})

    qr = segno.make(f"{APP_DOWNLOAD_URL}?order={cart.order_id}", error="m")
    qr_svg = qr.svg_inline(scale=4, dark="#17171A", light=None)

    summary = t.get("name", "Telekom order") if t else "Telekom order"
    if d and d.get("name") != "No device":
        summary += f" with {d.get('name')}"

    order = {
        "order_id": cart.order_id, "summary": summary,
        "monthly": tot["monthly"], "one_off": tot["one_off"],
        "monthly_spoken": money_spoken(tot["monthly"]),
        "term": f"{as_int(t.get('term_months')) if t else 24}-month term",
        "status_lines": status, "qr": qr_svg,
    }
    payload = {
        "order": order,
        "order_id": cart.order_id,
        "consents_recorded": len(cart.consents),
        "app_download_url": APP_DOWNLOAD_URL,
        "channel_attribution": "agent",
        "next_step": ("Tell the customer the order is confirmed and show them display_markdown. "
                      "Point at the QR code for installing MeinMagenta to track the order."),
    }
    return respond(ctx, payload, uri="ui://telekom/order.html",
                   markdown=md_order(order), widget_data=payload)


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

mcp = MCPServer(
    "telekom-commerce-demo",
    title="Telekom commerce (demo)",
    version="0.1.0",
    instructions=(
        "A demonstration Telekom commerce server for mobile, fixed-line and TV/OTT acquisition. "
        "Typical order of operations: search_tariffs → get_tariff_details → search_devices "
        "(mobile only) → create_cart → update_cart (customer details) → get_payment_methods → "
        "get_required_consents → complete_order.\n\n"
        "Display contract. Every tool returns `display_markdown`, Telekom's own rendering of that "
        "result, and `display_note`, which says what to do with it. When a widget is on screen, do "
        "not restate prices. Otherwise reproduce `display_markdown` verbatim — it is the priced "
        "offer as Telekom words it, including the minimum-term and post-term footnotes.\n\n"
        "Price integrity. Prices are euro cents and authoritative exactly as returned. Never sum "
        "components, apply a discount, convert a currency or round a figure yourself; quote only "
        "figures present in the tool result. Do not describe MagentaEINS as applied — it is a "
        "conditional saving that needs a Telekom fixed line at the same address. Do not call a "
        "payment complete on the strength of a token: the token is an authorisation, and the order "
        "is placed only when complete_order returns an order_id.\n\n"
        "On voice surfaces read the *_spoken fields rather than the cent values, keep lists to "
        "three items, and never read an ID aloud. This is demo data, not a live catalogue."
    ),
    extensions=[apps],
)


# ---- prompt templates ----------------------------------------------------

@mcp.prompt(name="mobile_acquisition", title="Buy a mobile tariff")
def mobile_acquisition(data_needs: str = "around 30 GB", device: str = "an iPhone") -> str:
    """Walk a customer through buying a mobile tariff with a handset."""
    return (
        f"I want a new Telekom mobile plan with {data_needs} of data, and I'd like {device} with it.\n\n"
        "Please search the tariffs, show me the detail of the one you recommend and why, then show me the "
        "handsets available on it. Once I have chosen, build the cart, collect my name, date of birth, "
        "delivery address and phone number, set up card payment, walk me through the required consents "
        "one at a time, and place the order."
    )


@mcp.prompt(name="fixed_acquisition", title="Buy a fixed-line or fibre tariff")
def fixed_acquisition(household: str = "a two-person household that streams a lot") -> str:
    """Walk a customer through buying a fixed-line or fibre connection."""
    return (
        f"I'm looking for a Telekom home internet connection for {household}.\n\n"
        "Show me the fixed-line and fibre options with speeds and what changes after the minimum term. "
        "Recommend one, then take me through to an order: cart, my details, card payment, the consents "
        "including the installation appointment, and confirmation."
    )


@mcp.prompt(name="ott_acquisition", title="Add TV or streaming")
def ott_acquisition(interest: str = "films, series and some live sport") -> str:
    """Walk a customer through adding a TV or streaming subscription."""
    return (
        f"I'd like to add Telekom TV or streaming to my account. I mostly watch {interest}.\n\n"
        "Show me what's available, explain what each one includes, then set up the order with my details, "
        "card payment and the required consents including the age confirmation."
    )


# ---- resources -----------------------------------------------------------

@mcp.resource("telekom://catalogue/tariffs", title="Tariff catalogue (markdown)", mime_type="text/markdown")
def res_tariffs() -> str:
    """The full tariff catalogue every tool answers from."""
    return (CATALOGUE / "tariffs.md").read_text(encoding="utf-8")


@mcp.resource("telekom://catalogue/devices", title="Device catalogue (markdown)", mime_type="text/markdown")
def res_devices() -> str:
    """The full device catalogue, including per-tariff instalment pricing."""
    return (CATALOGUE / "devices.md").read_text(encoding="utf-8")


@mcp.resource("telekom://catalogue/consents", title="Consent catalogue (markdown)", mime_type="text/markdown")
def res_consents() -> str:
    """Pre-contractual information and consent texts required before ordering."""
    return (CATALOGUE / "consents.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Telekom agentic commerce demo MCP server")
    ap.add_argument("--http", action="store_true", help="serve over streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-mcp-ui", action="store_true",
                    help="omit the in-band ui:// widget resource (same as TELEKOM_MCP_UI=0)")
    args = ap.parse_args()
    if args.no_mcp_ui:
        MCP_UI_ENABLED = False
    if args.http:
        print(f"Telekom demo MCP server on http://{args.host}:{args.port}/mcp")
        print(f"  {len(TARIFFS)} tariffs · {len(DEVICES)} devices · {len(CONSENTS)} consents")
        print(f"  in-band MCP-UI resource: {'on' if MCP_UI_ENABLED else 'off'}")
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
