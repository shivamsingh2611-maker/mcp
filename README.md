# Telekom agentic commerce — demo MCP server

A runnable MCP server that turns the static prototype into a real journey you can
drive by talking to Claude, Gemini or ChatGPT.

Nothing here touches a Telekom system. Every tool answers from the markdown files
in `catalogue/`, so the offer can be changed by editing a file and restarting —
no code, no deployment, no engineer.

```
server.py              the whole server: 9 tools, 3 prompts, 8 UI widgets
catalogue/tariffs.md   11 tariffs across mobile, fixed and TV/OTT
catalogue/devices.md   6 devices, priced per tariff
catalogue/consents.md  TKG 54, AGB, Widerruf, card mandate, and per-line-type extras
```

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python server.py                      # stdio, for a local desktop client
python server.py --http --port 8000   # remote, for a custom connector
python server.py --http --no-mcp-ui   # ...without the in-band ui:// widget
```

The HTTP endpoint is `http://127.0.0.1:8000/mcp`.

To reach it from a hosted assistant temporarily, put a tunnel in front:

```bash
npx cloudflared tunnel --url http://localhost:8000
```

Use the `https://….trycloudflare.com/mcp` URL it prints. This is fine for a live
demo but the URL is random and dies when your machine or the tunnel process stops.

## Deploy for real (Render)

Cart state lives in memory in a single Python process (see `CARTS` in
`server.py`), so this needs one persistent instance, not an autoscaled or
serverless one. Render's free web service tier fits: one always-running
container, a stable HTTPS domain, no card required.

This repo already includes `render.yaml` and `.python-version` (mcp>=2.2.0
requires Python 3.10+, pinned here to 3.11.9).

1. Push this folder to a new GitHub repo.
2. On [render.com](https://render.com), **New +** → **Blueprint**, connect the
   repo. Render reads `render.yaml` and creates the web service automatically
   (build: `pip install -r requirements.txt`; start:
   `python server.py --http --host 0.0.0.0 --port $PORT`).
   - No `render.yaml`/Blueprint access? Use **New +** → **Web Service** instead
     and paste the same build/start commands by hand.
3. Deploy. Render gives you `https://<service-name>.onrender.com`.
4. Your MCP endpoint is `https://<service-name>.onrender.com/mcp`.

Verify it's alive:

```bash
curl -i https://<service-name>.onrender.com/mcp
```

(A 4xx/406 response is expected for a plain GET — the endpoint only speaks
JSON-RPC over POST. Anything other than a connection error or 502 means the
process is up.)

Then connect it: in Claude, **Settings → Connectors → Add custom connector**,
paste that `/mcp` URL.

**Free-tier caveats:** the service spins down after ~15 minutes idle and takes
30–60s to wake on the next request (the first tool call in a new session may
time out or feel slow — retry it). Every restart or redeploy also wipes
in-memory carts, which is expected for this demo. If you need it always warm,
upgrade the Render service to a paid instance (still the same `render.yaml`).

## Connect it

**Claude** — Settings → Connectors → Add custom connector → paste the `/mcp` URL.
All nine tools and the three prompt templates work. The MCP Apps widget does
*not* render (see "Where the UI renders" below); the priced tables come through
as `display_markdown` instead.

**ChatGPT** — Settings → Connectors → Create, same URL. Same position as Claude:
tools work, widget rendering depends on Apps SDK support in your workspace.

**Gemini** — add as an MCP server in the Gemini CLI or any UCP/MCP-capable client.

**Any client** — `npx @mcpjam/inspector@latest` and point it at the URL. Best way
to watch the raw JSON-RPC while you demo, and the easiest place to see a widget
actually painted.

## Where the UI renders

The server emits its widgets two different ways, because no single mechanism
renders everywhere today:

| Mechanism | How it travels | Renders in |
|---|---|---|
| MCP Apps (SEP-2133) | `_meta.ui.resourceUri` on the tool + a separate `ui://` resource, gated by capability negotiation | Nothing yet — the `extensions` capability is only carried on wire revision `2026-07-28`, which the `initialize` handshake cannot reach, so `client_supports_apps()` is false in Claude and ChatGPT |
| MCP-UI (in-band) | an `EmbeddedResource` with a `ui://` URI and `text/html`, inside the tool result's own `content` | MCP-UI-aware clients (MCPJam inspector, Goose, custom web chat) |
| `display_markdown` | a plain field in every tool result | Everywhere, including voice |

The in-band copy is a complete, standalone HTML document with that call's data
already baked in, so it needs no postMessage bridge from the host. Disable it
with `--no-mcp-ui` or `TELEKOM_MCP_UI=0` if a client dumps the raw HTML into the
transcript instead of rendering it.

Verify what a client is actually getting:

```bash
curl -s -X POST https://<service>.onrender.com/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'mcp-session-id: <id from initialize>' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_tariffs","arguments":{"line_type":"mobile"}}}'
```

## The display contract

Every tool returns two extra fields, and they are what keeps pricing under
Telekom's control rather than the model's:

- **`display_markdown`** — the priced table as Telekom words it, rendered
  server-side, including the minimum-term and post-term footnotes.
- **`display_note`** — what the model should do with it, decided per request:
  when the client negotiated MCP Apps, "the widget shows this, don't restate
  prices"; otherwise "show `display_markdown` verbatim".

Tool descriptions and the server instructions carry the price-integrity rules:
prices are euro cents and authoritative as returned, never summed or rounded by
the model; MagentaEINS is a conditional saving, never an applied one; a payment
token is an authorisation, not a completed payment.

Voice surfaces get `*_spoken` variants (`monthly_spoken`, `monthly_total_spoken`)
so "€39.95" is read as "39 euro 95" rather than digit by digit.

## Driving the demo

Three prompt templates seed a journey. Pick one from the client's prompt menu:

| Prompt | What it opens |
|---|---|
| `mobile_acquisition` | Tariff, handset, cart, checkout, consents, order |
| `fixed_acquisition` | DSL and fibre, including the installation-appointment consent |
| `ott_acquisition` | MagentaTV and MagentaSport, including the age confirmation |

Or just type: *"I need a Telekom mobile plan with about 30 GB and an iPhone."*

Expected tool sequence:

```
search_tariffs → get_tariff_details → search_devices → get_device_details
  → create_cart → update_cart (name, DOB, address, phone)
  → get_payment_methods (tokenise=true) → get_required_consents (grant=[...])
  → complete_order
```

## What to point at while presenting

**The presentation is ours, on every surface.** Price and product reach the
customer as Telekom authored them, not as a language model's paraphrase — as a
rendered widget where the client supports one, and as server-rendered
`display_markdown` everywhere else. The model is told which, per request.

**It degrades honestly.** SEP-2133 requires a UI-bound tool to still be useful
without the extension. `respond()` in `server.py` branches on
`client_supports_apps()`: widget present, suppress prose; no widget, print the
server's own markdown. The failure mode this avoids is the demo telling the
model "the widget already shows the price" when nothing is on screen — which
silently hides pricing.

**Cards only, and the server says why.** `get_payment_methods` returns SEPA as
`unsupported` with the reason attached: a card credential can be tokenised and
delegated to an agent under the AP2 mandate model, but a SEPA mandate is an
authorisation granted to the creditor and cannot travel through an agent. The token
it issues is scoped to merchant, cart and a maximum amount, and expires in 15 minutes.

**Consents are gated server-side, not by prompt.** `complete_order` refuses with a
list of blockers until the cart has a tariff, all four customer fields, a payment
token and every mandatory consent. Try asking the model to skip them — it cannot.

**The order confirmation carries a QR code** generated at order time, encoding the
MeinMagenta download URL with the order ID appended, to move the customer from the
agent surface into our own app.

## Guard rails worth demonstrating

| Try this | What happens |
|---|---|
| Order before granting consents | Refused, with each missing consent named |
| Give a date of birth under 18 | Refused — contract capacity check |
| Send a full card number | Refused — the tool accepts at most four digits |
| Combine a device with a fixed-line tariff | Refused — not device-eligible |
| Ask for a price the model invents | The widget shows the server's price; the tool result tells the model not to restate it |

## Changing the offer

Edit `catalogue/tariffs.md` and restart. Every block under a `## ID` heading becomes
one tariff; fields are `key: value`; prices are in euro cents. The same applies to
devices and consents. The three files are also exposed as MCP resources, so the
assistant can read the raw catalogue if asked.

## What this demo deliberately does not do

- No OAuth. Every session is anonymous, so there is no customer context, no
  eligibility check against a real account, and no upgrade window.
- No handoff to OneShop. The order completes in-session to show the full flow;
  a production build would hand off a signed, single-use checkout URL at the
  consent step instead.
- No ACP or UCP checkout endpoints. The tool layer is deliberately protocol-neutral;
  adapters would sit at the edge.
- Prices, availability and device line-up are illustrative.
