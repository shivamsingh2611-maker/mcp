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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.apps import Apps, ResourceCsp, client_supports_apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents, ToolAnnotations
from starlette.requests import Request
from starlette.responses import HTMLResponse

HERE = Path(__file__).parent
CATALOGUE = HERE / "catalogue"

APP_MIME = "text/html;profile=mcp-app"

# Optionally emit the widget a second time as an in-band embedded resource, the
# way MCP-UI clients consume it. Off by default: it repeats the `ui://` URI that
# MCP Apps hosts resolve through `resources/read`, and a second copy of the same
# URI inside the result is a plausible way to confuse a host. Turn it on with
# TELEKOM_MCP_UI=1 only for a client that needs in-band delivery.
MCP_UI_ENABLED = os.environ.get("TELEKOM_MCP_UI", "0").strip().lower() in ("1", "true", "yes", "on")

# Public origin this server is reachable on, used to build the hand-off cart link.
# Render sets RENDER_EXTERNAL_URL itself; --http fills it in locally.
PUBLIC_BASE_URL = (os.environ.get("TELEKOM_PUBLIC_URL")
                   or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")


def cart_url(cart_id: str) -> str | None:
    """The browser hand-off URL for a cart, or None when the origin is unknown."""
    return f"{PUBLIC_BASE_URL}/cart/{cart_id}" if PUBLIC_BASE_URL else None

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

    def blockers(self) -> list[str]:
        """Details still missing before the cart can be handed to checkout.

        Payment and consent are collected on the checkout page, not in the
        conversation, so they are not listed here.
        """
        problems = []
        if not self.tariff_id:
            problems.append("No tariff selected. Call search_tariffs, then create_cart.")
        for f, label in (("name", "full name"), ("dob", "date of birth"),
                         ("address", "delivery address"), ("phone", "phone number")):
            if not self.customer.get(f):
                problems.append(f"Missing {label}. Call update_cart with customer details.")
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
            "totals": tot,
            "magenta_eins_discount": as_int(t.get("magenta_eins_discount")) if t else 0,
            "blockers": self.blockers(),
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

# MCP Apps host bridge (SEP-1865, spec revision 2026-01-26).
#
# The lifecycle is strict and the previous hand-rolled version got it wrong,
# which is why nothing ever rendered: the View MUST send `ui/initialize` *with*
# params, and MUST then send `ui/notifications/initialized`. Until the host sees
# that notification it is forbidden from sending anything to the View — so no
# `ui/notifications/tool-result` ever arrived and every widget sat on its
# build-time snapshot (which is null for cart/order, i.e. a blank card).
#
# FALLBACK is the data baked in at build time (catalogue snapshot) or, for the
# in-band copy, this call's own payload. It paints immediately when it carries
# something; the authoritative repaint comes from `ui/notifications/tool-result`.
BRIDGE = """
var PAINTED=false;
function paint(d){
  if(!d)return false;
  try{render(d)}
  catch(e){R.innerHTML='<div class="card"><div class="bd empty-state">'+e.message+'</div></div>';return true}
  if(!R.innerHTML.trim())return false;
  PAINTED=true;return true;
}
function dataFrom(r){
  if(!r)return null;
  if(r.structuredContent)return r.structuredContent;
  var c=r.content||[];
  for(var i=0;i<c.length;i++){
    if(c[i]&&c[i].type==='text'&&c[i].text){try{return JSON.parse(c[i].text)}catch(e){}}
  }
  return null;
}
function boot(){
  var w=window,ID=1;
  paint(FALLBACK);
  w.addEventListener('message',function(e){
    var m=e.data;
    if(!m||m.jsonrpc!=='2.0')return;
    if(m.id===ID&&m.result){
      // Handshake acknowledged. The host may only push data once it sees this.
      w.parent.postMessage({jsonrpc:'2.0',method:'ui/notifications/initialized'},'*');
      return;
    }
    if(m.method==='ui/notifications/tool-result'){
      var d=dataFrom(m.params);
      if(d)paint(d);
    }
  });
  try{
    w.parent.postMessage({jsonrpc:'2.0',id:ID,method:'ui/initialize',params:{
      protocolVersion:'2026-01-26',
      appCapabilities:{availableDisplayModes:['inline']},
      clientInfo:{name:'telekom-commerce-view',version:'1.0.0'}
    }},'*');
  }catch(e){}
  setTimeout(function(){
    if(!PAINTED)R.innerHTML='<div class="card"><div class="bd empty-state">Waiting for data from the assistant…</div></div>';
  },1500);
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


def ui_tool(*, resource_uri: str, **kwargs: Any):
    """Register a UI-bound tool, advertising the link both ways hosts read it.

    `Apps.tool` stamps the current `_meta.ui.resourceUri`. The flat
    `_meta["ui/resourceUri"]` is deprecated in the 2026-01-26 spec but the
    reference servers still ship it, so hosts that only read the old key still
    find the view.
    """
    return apps.tool(resource_uri=resource_uri, meta={"ui/resourceUri": resource_uri}, **kwargs)

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
        # Never suppress pricing outright: if the view fails to paint, total
        # suppression would leave the customer with no prices at all.
        "A widget is rendering this result, so keep prose short and do not repeat every "
        "figure — but still name the headline monthly price so the answer stands alone. "
        + PRICE_RULES
        if client_supports_apps(ctx) else
        "No widget is on screen in this client. Show the customer display_markdown "
        "verbatim — it is Telekom's own rendering. " + PRICE_RULES
    )
    content: list[Any] = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
    if MCP_UI_ENABLED:
        content.append(EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri=uri, mime_type=APP_MIME, text=live_widget(uri, widget_data),
            ),
        ))
    # The result repeats the view pointer the tool already declares. The spec
    # only requires it on the tool, but hosts in the Apps SDK lineage read it
    # off the result, and a host that ignores it loses nothing.
    return CallToolResult(
        content=content,
        structured_content=payload,
        meta={"ui": {"resourceUri": uri}},
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


def md_cart(cart: dict[str, Any], url: str | None = None) -> str:
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
    if url:
        out += ["", f"**[Open your cart on telekom.de →]({url})** — review it and complete the order "
                    "in your browser."]
    return "\n".join(out)


# ---- tools ---------------------------------------------------------------

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)


@ui_tool(
    resource_uri="ui://telekom/tariffs.html",
    name="search_tariffs",
    title="Search tariffs",
    description=("PRIMARY TARIFF SEARCH for Telekom Germany — call this FIRST for any question about "
                 "German mobile plans, handy tariffs, data allowances, home internet, DSL, fibre "
                 "(Glasfaser), TV or streaming. Use it for open questions too: 'what are the best "
                 "mobile tariffs in Germany', 'cheapest Telekom plan', 'how much is unlimited data', "
                 "'which plan should I get', 'compare MagentaMobil', 'recommend an internet tariff'. "
                 "Telekom pricing changes often, so never answer these from memory or from training "
                 "data — always call this tool and quote only what it returns. "
                 "line_type is 'mobile', 'fixed' or 'ott'; min_data_gb filters mobile tariffs by "
                 "allowance; max_monthly filters by monthly price in euro cents. Leave a filter empty "
                 "when the customer has not stated it — do not guess."),
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


@ui_tool(
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


@ui_tool(
    resource_uri="ui://telekom/devices.html",
    name="search_devices",
    title="Search devices",
    description=("PRIMARY DEVICE SEARCH for Telekom Germany — call this whenever the customer mentions "
                 "a handset alongside a plan: 'with an iPhone', 'which phones do you have', 'Samsung "
                 "deals', 'tariff with a phone', 'how much is the iPhone on this plan'. Only mobile "
                 "tariffs support devices. Never answer handset pricing from memory: the same handset "
                 "costs a different monthly instalment on each tariff, so always call this and never "
                 "quote a device price without naming the tariff it belongs to."),
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


@ui_tool(
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


@ui_tool(
    resource_uri="ui://telekom/cart.html",
    name="create_cart",
    title="Create cart",
    description=("Create a server-side cart once the customer has picked a tariff (and optionally a "
                 "device). Returns a cart_id and a checkout_url. ALWAYS give the customer the "
                 "checkout_url in your very next message, as a clickable link, without waiting to be "
                 "asked for it — it is how they finish the order. prices are recomputed here on every "
                 "read. magenta_eins_discount is a conditional saving, not an applied one — describe "
                 "it as available with a Telekom fixed line, never as already deducted."),
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
    url = cart_url(cart.cart_id)
    payload = {
        "cart": pub, "show_customer": True,
        "checkout_url": url,
        "monthly_total_spoken": money_spoken(pub["totals"]["monthly"]),
        "suggested_additions": ([{"type": "bundle_discount", "product": "MagentaEINS",
                                  "saves_monthly": pub["magenta_eins_discount"],
                                  "condition": "add_fixed_line_same_address"}]
                                if pub["magenta_eins_discount"] else []),
        "next_step": ("Give the customer checkout_url now, in this turn, as a clickable link — do not "
                      "wait for them to ask for it. Optionally call update_cart first if they want to "
                      "add their name, date of birth, delivery address or phone. Never invent a link."),
    }
    return respond(ctx, payload, uri="ui://telekom/cart.html",
                   markdown=md_cart(pub, url), widget_data=payload)


@ui_tool(
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
    url = cart_url(cart.cart_id)
    payload = {"cart": pub, "show_customer": True, "checkout_url": url,
               "monthly_total_spoken": money_spoken(pub["totals"]["monthly"]),
               "next_step": ("Give the customer checkout_url so they can review the cart and complete "
                             "the order in their browser. Hand over the link as returned.")}
    return respond(ctx, payload, uri="ui://telekom/cart.html",
                   markdown=md_cart(pub, url), widget_data=payload)



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
        "(mobile only) → create_cart → update_cart (customer details, optional).\n\n"
        "When to call these tools. Any question about Telekom or German mobile, internet, fibre or "
        "TV pricing goes through search_tariffs first — including broad ones like 'what are the best "
        "mobile tariffs in Germany'. Tariffs, devices and prices change often, so never answer from "
        "memory or training data and never estimate a price; if the tools have not returned it, do "
        "not say it.\n\n"
        "Ending the journey. The conversation ends at a built cart. The moment create_cart or "
        "update_cart returns, give the customer the `checkout_url` from that result as a clickable "
        "link, in the same turn, without being asked — that link is how they complete the order, and "
        "there is no in-chat checkout. Pass it through exactly as returned; never construct one.\n\n"
        "Display contract. Every tool returns `display_markdown`, Telekom's own rendering of that "
        "result, and `display_note`, which says what to do with it. When a widget is on screen, do "
        "not restate prices. Otherwise reproduce `display_markdown` verbatim — it is the priced "
        "offer as Telekom words it, including the minimum-term and post-term footnotes.\n\n"
        "Price integrity. Prices are euro cents and authoritative exactly as returned. Never sum "
        "components, apply a discount, convert a currency or round a figure yourself; quote only "
        "figures present in the tool result. Do not describe MagentaEINS as applied — it is a "
        "conditional saving that needs a Telekom fixed line at the same address. Nothing is ordered "
        "in this conversation: a cart is a cart until the customer completes it on the checkout "
        "page, so never tell them an order has been placed.\n\n"
        "On voice surfaces read the *_spoken fields rather than the cent values, keep lists to "
        "three items, and never read an ID aloud. This is demo data, not a live catalogue."
    ),
    extensions=[apps],
)


# --------------------------------------------------------------------------
# Browser hand-off: the cart as a real web page
# --------------------------------------------------------------------------
#
# The agent journey ends at a built cart and hands the customer a link. The page
# below is served from this same process at /cart/{cart_id}, in the Telekom
# design language the widgets use, so the hand-off looks like Telekom rather
# than like a chat transcript.

def esc(value: Any) -> str:
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


CART_PAGE_CSS = """
:root{--m:#E20074;--mdk:#9D1046;--mbg:#FDF2F8;--ink:#17171A;--grey:#6E6E73;
--faint:#A1A1A8;--line:#E4E4E7;--bg:#F4F4F5;--green:#15803D;--amber:#B45309;--ambg:#FEF3C7}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);
color:var(--ink);line-height:1.5;font-size:15px}
header{background:var(--m);color:#fff;padding:14px 20px;display:flex;align-items:center;gap:12px}
.logo{display:flex;gap:3px;align-items:center}
.logo i{width:7px;height:7px;background:#fff;display:block;border-radius:1px}
.logo b{font-size:16px;font-weight:700;letter-spacing:.3px;margin-left:5px}
header .sp{margin-left:auto;font-size:13px;opacity:.92}
main{max-width:720px;margin:0 auto;padding:20px 16px 56px}
h1{font-size:22px;font-weight:700;margin-bottom:4px}
.sub{color:var(--grey);font-size:13.5px;margin-bottom:18px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;margin-bottom:16px}
.card h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
color:var(--grey);padding:14px 18px 0}
.line{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;padding:14px 18px;
border-bottom:1px solid var(--line)}
.line:last-child{border-bottom:none}
.line .nm{font-size:15.5px;font-weight:600}
.line .dt{font-size:12.5px;color:var(--grey);margin-top:2px}
.line .pr{text-align:right;white-space:nowrap;font-size:15.5px;font-weight:700}
.line .pr small{display:block;font-size:11px;font-weight:500;color:var(--grey);margin-top:1px}
.sum{padding:14px 18px}
.sum .row{display:flex;justify-content:space-between;font-size:14px;padding:4px 0;color:var(--grey)}
.sum .row span:last-child{color:var(--ink)}
.sum .tot{display:flex;justify-content:space-between;align-items:baseline;
border-top:2px solid var(--line);margin-top:10px;padding-top:12px}
.sum .tot span{font-size:16px;font-weight:700}
.sum .tot b{font-size:26px;font-weight:700;color:var(--m)}
.promo{border:1.5px solid var(--m);background:var(--mbg);border-radius:11px;padding:13px 15px;margin:0 18px 16px}
.promo .h{font-size:13.5px;font-weight:700;color:var(--mdk);margin-bottom:3px}
.promo .b{font-size:13px}
.note{font-size:12.5px;color:var(--grey);background:var(--bg);border-radius:8px;padding:10px 12px;margin:0 18px 16px}
.warn{background:var(--ambg);border:1.5px solid var(--amber);border-radius:10px;padding:12px 14px;
margin:0 18px 16px;font-size:13px;color:#5C3A08}
.warn b{display:block;color:var(--amber);margin-bottom:4px}
.f{padding:10px 18px}
.f label{display:block;font-size:11.5px;font-weight:600;color:var(--grey);margin-bottom:3px}
.f .v{border:1.5px solid var(--line);border-radius:9px;padding:10px 12px;font-size:14.5px;background:#FCFCFD}
.f .v.empty{color:var(--faint);font-style:italic}
.cta{padding:4px 18px 20px}
.cta button{width:100%;background:var(--m);color:#fff;border:0;border-radius:10px;padding:15px;
font-size:16px;font-weight:700;cursor:pointer;font-family:inherit}
.cta button:disabled{background:var(--faint);cursor:not-allowed}
.cta .hint{text-align:center;font-size:12px;color:var(--grey);margin-top:9px}
footer{max-width:720px;margin:0 auto;padding:0 18px 40px;font-size:11.5px;color:var(--faint)}
@media(max-width:520px){main{padding:14px 10px 40px}h1{font-size:19px}.sum .tot b{font-size:22px}}
"""


def cart_page(cart: dict[str, Any]) -> str:
    """Render a cart as a standalone Telekom-styled checkout page."""
    t, d, tot = cart.get("tariff"), cart.get("device"), cart.get("totals", {})
    lines = []
    if t:
        lines.append(f"""<div class="line"><div><div class="nm">{esc(t['name'])}</div>
        <div class="dt">{esc(t.get('line_type', '')).title()} · 24-month minimum term</div></div>
        <div class="pr">{money(t['monthly'])}<small>per month</small></div></div>""")
    if d and d.get("name") != "No device":
        lines.append(f"""<div class="line"><div><div class="nm">{esc(d['name'])}</div>
        <div class="dt">{esc(d.get('storage') or '')} {esc(d.get('colour') or '')}</div></div>
        <div class="pr">{money(d['monthly'])}<small>per month</small></div></div>""")
    if not lines:
        lines.append('<div class="line"><div class="nm">Your cart is empty</div></div>')

    cu = cart.get("customer") or {}
    fields = ""
    if cu:
        def fld(label, key):
            v = cu.get(key)
            return (f'<div class="f"><label>{label}</label>'
                    f'<div class="v {"" if v else "empty"}">{esc(v) if v else "not provided yet"}</div></div>')
        fields = ('<div class="card"><h2>Your details</h2>'
                  + fld("Full name", "name") + fld("Date of birth", "dob")
                  + fld("Delivery address", "address") + fld("Phone", "phone") + "</div>")

    promo = ""
    if cart.get("magenta_eins_discount"):
        promo = (f'<div class="promo"><div class="h">You qualify for MagentaEINS</div>'
                 f'<div class="b">Adding a Telekom fixed line at your address reduces this by '
                 f'{money(cart["magenta_eins_discount"])} per month, for as long as both contracts run.</div></div>')

    after = tot.get("monthly_after_24")
    after_note = (f'<div class="note">From month 25 the monthly total becomes {money(after)}.</div>'
                  if after and after != tot.get("monthly") else "")

    # `blockers` is written for the agent ("Call update_cart with customer details"),
    # so the customer-facing page names the missing details instead.
    missing = [label for key, label in (("name", "your full name"), ("dob", "your date of birth"),
                                        ("address", "a delivery address"), ("phone", "a phone number"))
               if not cu.get(key)]
    blocker_box = ""
    if missing:
        items = "".join(f"<li>{esc(m)}</li>" for m in missing)
        blocker_box = (f'<div class="warn"><b>We still need a few details</b>'
                       f'<ul style="margin:0 0 0 18px">{items}</ul></div>')

    one_off = (f'<div class="row"><span>One-off charges</span><span>{money(tot.get("one_off", 0))}</span></div>'
               if tot.get("one_off") else "")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Telekom cart</title><style>{CART_PAGE_CSS}</style></head><body>
<header><span class="logo"><i></i><i></i><b>Telekom</b></span><span class="sp">Warenkorb</span></header>
<main>
  <h1>Your cart</h1>
  <div class="sub">Cart {esc(cart.get('cart_id'))} · prices include VAT</div>
  <div class="card">
    <h2>Your selection</h2>
    {''.join(lines)}
    <div class="sum">
      <div class="row"><span>Monthly, months 1–24</span><span>{money(tot.get('monthly', 0))}</span></div>
      {one_off}
      <div class="tot"><span>Monthly total</span><b>{money(tot.get('monthly', 0))}</b></div>
    </div>
  </div>
  {promo}{after_note}{blocker_box}
  {fields}
  <div class="card"><div class="cta">
    <button disabled>Zahlungspflichtig bestellen</button>
    <div class="hint">Demo only — no order is placed and no payment is taken.</div>
  </div></div>
</main>
<footer>Demo environment. Prices, availability and device line-up are illustrative and do not
reflect a live Telekom offer. Full price information per TKG §54 is in the Produktinformationsblatt.</footer>
</body></html>"""


@mcp.custom_route("/cart/{cart_id}", methods=["GET"])
async def serve_cart(request: Request) -> HTMLResponse:
    """Serve a cart as a web page for the browser hand-off."""
    cart = CARTS.get(request.path_params["cart_id"])
    if not cart:
        return HTMLResponse(
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Cart not found</title>"
            f"<style>{CART_PAGE_CSS}</style></head><body>"
            "<header><span class='logo'><i></i><i></i><b>Telekom</b></span></header>"
            "<main><h1>This cart has expired</h1><div class='sub'>Carts are held in memory for the "
            "life of the server process, so a restart clears them. Ask the assistant to build a new "
            "one.</div></main></body></html>",
            status_code=404,
        )
    return HTMLResponse(cart_page(cart.public()))


# ---- prompt templates ----------------------------------------------------

@mcp.prompt(name="mobile_acquisition", title="Buy a mobile tariff")
def mobile_acquisition(data_needs: str = "around 30 GB", device: str = "an iPhone") -> str:
    """Walk a customer through buying a mobile tariff with a handset."""
    return (
        f"I want a new Telekom mobile plan with {data_needs} of data, and I'd like {device} with it.\n\n"
        "Please search the tariffs, show me the detail of the one you recommend and why, then show me the "
        "handsets available on it. Once I have chosen, build me a cart and send me the link to "
        "complete the order in my browser."
    )


@mcp.prompt(name="fixed_acquisition", title="Buy a fixed-line or fibre tariff")
def fixed_acquisition(household: str = "a two-person household that streams a lot") -> str:
    """Walk a customer through buying a fixed-line or fibre connection."""
    return (
        f"I'm looking for a Telekom home internet connection for {household}.\n\n"
        "Show me the fixed-line and fibre options with speeds and what changes after the minimum term. "
        "Recommend one, then build me a cart and send me the link to complete it in my browser."
    )


@mcp.prompt(name="ott_acquisition", title="Add TV or streaming")
def ott_acquisition(interest: str = "films, series and some live sport") -> str:
    """Walk a customer through adding a TV or streaming subscription."""
    return (
        f"I'd like to add Telekom TV or streaming to my account. I mostly watch {interest}.\n\n"
        "Show me what's available, explain what each one includes, then build me a cart and send me "
        "the link to complete it in my browser."
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
        if not PUBLIC_BASE_URL:
            shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
            PUBLIC_BASE_URL = f"http://{shown}:{args.port}"
        print(f"Telekom demo MCP server on http://{args.host}:{args.port}/mcp")
        print(f"  cart hand-off pages at {PUBLIC_BASE_URL}/cart/<cart_id>")
        print(f"  {len(TARIFFS)} tariffs · {len(DEVICES)} devices")
        print(f"  in-band MCP-UI resource: {'on' if MCP_UI_ENABLED else 'off'}")
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
