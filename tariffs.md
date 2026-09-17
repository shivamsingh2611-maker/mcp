Telekom tariff catalogue
Demo data. Edit this file and restart the server — no code changes needed. Every ## ID block becomes one tariff. Fields are key: value. Prices are in euro cents. line_type is one of mobile, fixed, ott.

Everything below the original five-tariff set was enriched from the live telekom.de mobile, internet/Glasfaser and MagentaTV pages so the assistant has real product structure, wording and current promotions to draw on — numbers are still illustrative demo data, not a live price feed (see the README). Prose paragraphs between blocks are ignored by the parser but are still readable by the model via the telekom://catalogue/tariffs resource, so use them freely for anything a customer might ask that isn't a flat field.

MM_XS
name: MagentaMobil XS line_type: mobile headline: 20 GB for occasional users data_gb: 20 speed: 5G up to 300 Mbit/s monthly_initial: 2495 monthly_after_24: 2995 one_off: 3995 term_months: 24 roaming: EU roaming at domestic rates; 2 GB/year outside the EU (roaming zones 2 and 3) extras: Allnet Flat (calls and SMS to all German networks); eSIM included; entry-level tier, not usually bundled with a premium handset magenta_eins_discount: 500 device_eligible: true

MM_S
name: MagentaMobil S line_type: mobile headline: 30 GB for light users data_gb: 30 speed: 5G up to 300 Mbit/s monthly_initial: 3495 monthly_after_24: 3995 one_off: 3995 term_months: 24 roaming: EU roaming at domestic rates; 4 GB/year outside the EU (roaming zones 2 and 3) extras: Allnet Flat; 64 kbit/s after data allowance; eSIM included magenta_eins_discount: 500 device_eligible: true

MM_M
name: MagentaMobil M line_type: mobile headline: 50 GB, our most popular mobile tariff data_gb: 50 speed: 5G up to 500 Mbit/s monthly_initial: 3995 monthly_after_24: 4995 one_off: 3995 term_months: 24 roaming: EU roaming at domestic rates; 10 GB/year outside the EU (roaming zones 2 and 3) extras: Allnet Flat; StreamOn Music; unlimited data with a PlusKarte booked; eSIM included magenta_eins_discount: 1000 device_eligible: true

MM_L
name: MagentaMobil L line_type: mobile headline: 100 GB with full StreamOn data_gb: 100 speed: 5G up to 1000 Mbit/s monthly_initial: 4995 monthly_after_24: 5995 one_off: 3995 term_months: 24 roaming: EU roaming at domestic rates; 25 GB/year outside the EU (roaming zones 2 and 3) extras: Allnet Flat; StreamOn Music and Video; unlimited data with a PlusKarte booked; MultiSIM available; eSIM included magenta_eins_discount: 1000 device_eligible: true

MM_XL
name: MagentaMobil XL line_type: mobile headline: Unlimited data data_gb: 0 speed: 5G, no throttling monthly_initial: 7495 monthly_after_24: 8495 one_off: 3995 term_months: 24 roaming: EU roaming at domestic rates; 50 GB/year outside the EU (roaming zones 2 and 3) extras: Allnet Flat; unlimited data; StreamOn Music and Video; MultiSIM available; eSIM included magenta_eins_discount: 1000 device_eligible: true

How to choose a mobile tariff (from telekom.de)
Telekom groups customers into three usage types when recommending a tariff:

Wenignutzer (light users — mostly messaging, occasional browsing): MagentaMobil XS or S.
Normalnutzer (regular social media, navigation, music): MagentaMobil M or L.
Vielsurfer (heavy streaming, constant data use): MagentaMobil XL with unlimited data.
Rough data budget guide Telekom publishes for reference (per month):

Activity	1 GB	5 GB	10 GB	25 GB
Social media (~330 MB/hr)	3 hr	15 hr	30 hr	75 hr
Music streaming (~50 MB/hr)	20 hr	100 hr	200 hr	500 hr
Series streaming, SD (~1 GB/hr)	1 hr	5 hr	10 hr	25 hr
PlusKarten. Adding a PlusKarte (an additional SIM on the same account, for family or friends — no shared name/address required) makes every card cheaper as more are added, and MagentaMobil M and L switch to unlimited data once a PlusKarte is booked (MagentaMobil S too, if the account also has a Telekom fixed line). All cards share one bill.

MultiSIM. Puts the same phone number on a second device (typically a smartwatch) — available as an add-on on MagentaMobil L and XL.

Add-on options worth knowing about:

MagentaEINS — combine this mobile line with a Telekom fixed line for the monthly discount shown in magenta_eins_discount above.
Travel Mobil Basic — extra data allowance for travel outside the EU roaming zones.
HotSpot Flat — use Telekom WiFi hotspots without touching your own data allowance.
MZ_S
name: MagentaZuhause S line_type: fixed headline: 16 Mbit/s DSL for small households data_gb: 0 speed: DSL up to 16 Mbit/s down, 2.4 Mbit/s up monthly_initial: 995 monthly_after_24: 3895 one_off: 0 term_months: 24 roaming: Not applicable extras: Speedport router included (100 euro router credit); unlimited German landline calls; introductory price for the first 3 months, then the standard rate from month 4 magenta_eins_discount: 500 device_eligible: false

MZ_M
name: MagentaZuhause M line_type: fixed headline: 50 Mbit/s for everyday streaming households data_gb: 0 speed: DSL up to 50 Mbit/s down, 20 Mbit/s up monthly_initial: 995 monthly_after_24: 4395 one_off: 0 term_months: 24 roaming: Not applicable extras: Speedport router included (100 euro router credit, 300 euro total price advantage); unlimited German landline calls; introductory price for the first 3 months, then the standard rate from month 4 magenta_eins_discount: 1000 device_eligible: false

MZ_L
name: MagentaZuhause L line_type: fixed headline: 100 Mbit/s, Telekom's recommended DSL tariff data_gb: 0 speed: DSL up to 100 Mbit/s down, 40 Mbit/s up monthly_initial: 995 monthly_after_24: 4895 one_off: 0 term_months: 24 roaming: Not applicable extras: Speedport router included (100 euro router credit, 360 euro total price advantage); unlimited German landline calls; introductory price for the first 3 months, then the standard rate from month 4; Telekom's recommended DSL tier magenta_eins_discount: 1000 device_eligible: false

MZ_XL
name: MagentaZuhause XL line_type: fixed headline: 250 Mbit/s DSL for heavy households data_gb: 0 speed: DSL up to 250 Mbit/s down, 40 Mbit/s up monthly_initial: 995 monthly_after_24: 5595 one_off: 0 term_months: 24 roaming: Not applicable extras: Speedport router included (100 euro router credit, 300 euro total price advantage); unlimited German landline calls; introductory price for the first 3 months, then the standard rate from month 4 magenta_eins_discount: 1000 device_eligible: false

GF_150
name: Glasfaser 150 line_type: fixed headline: Telekom's recommended fibre tariff, 150 Mbit/s data_gb: 0 speed: Fibre up to 150 Mbit/s down, 75 Mbit/s up monthly_initial: 995 monthly_after_24: 4595 one_off: 0 term_months: 24 roaming: Not applicable extras: Internet flat and telephony flat included; also bookable with a 12-month term; 100 euro router credit, up to 100 euro cashback; introductory price for the first 3 months, then the standard rate from month 4; requires a fibre connection at the address (availability check required) magenta_eins_discount: 1000 device_eligible: false

GF_300
name: Glasfaser 300 line_type: fixed headline: 300 Mbit/s fibre for streaming and multi-device households data_gb: 0 speed: Fibre up to 300 Mbit/s down, 150 Mbit/s up monthly_initial: 995 monthly_after_24: 5095 one_off: 0 term_months: 24 roaming: Not applicable extras: Internet flat and telephony flat included; 100 euro router credit, up to 50 euro cashback; introductory price for the first 3 months, then the standard rate from month 4; requires a fibre connection at the address (availability check required) magenta_eins_discount: 1000 device_eligible: false

GF_600
name: Glasfaser 600 line_type: fixed headline: 600 Mbit/s fibre for home office and gaming data_gb: 0 speed: Fibre up to 600 Mbit/s down, 300 Mbit/s up monthly_initial: 995 monthly_after_24: 6095 one_off: 0 term_months: 24 roaming: Not applicable extras: Internet flat and telephony flat included; 100 euro router credit, up to 150 euro cashback; introductory price for the first 3 months, then the standard rate from month 4; requires a fibre connection at the address (availability check required) magenta_eins_discount: 1000 device_eligible: false

GF_1000
name: Glasfaser 1.000 line_type: fixed headline: 1000 Mbit/s, Telekom's fastest fibre tariff data_gb: 0 speed: Fibre up to 1000 Mbit/s down, 500 Mbit/s up monthly_initial: 995 monthly_after_24: 7095 one_off: 0 term_months: 24 roaming: Not applicable extras: Internet flat and telephony flat included; 100 euro router credit, up to 100 euro cashback; introductory price for the first 3 months, then the standard rate from month 4; requires a fibre connection at the address (availability check required) magenta_eins_discount: 1000 device_eligible: false

MZ_YOUNG
name: MagentaZuhause Young line_type: fixed headline: 100 Mbit/s for students and apprentices under 28 data_gb: 0 speed: DSL or fibre up to 100 Mbit/s down, 40 Mbit/s up monthly_initial: 2470 monthly_after_24: 2470 one_off: 0 term_months: 24 roaming: Not applicable extras: Online-only discount tariff for customers under 28 (proof of age/status required); 2 years of router rental included free; ideal for a first flat share magenta_eins_discount: 0 device_eligible: false

DSL vs. Glasfaser (from telekom.de)
MagentaZuhause (DSL)	Glasfaser
Medium	Copper, at least in part	Fibre all the way to the home
Top speed	Up to 250 Mbit/s	Up to 1000 Mbit/s
Stability	Can dip under heavy load	More stable, lower latency
Where available	Nationwide	Address-dependent — needs an availability check
If fibre isn't yet available at an address, Telekom offers a DSL transition tariff for around 29.95 euro/month for the first 3 months, switching over to Glasfaser automatically once it's ready.

TV_BASIC
name: MagentaTV Basic line_type: ott headline: Over 100 channels, live and on demand data_gb: 0 speed: Not applicable monthly_initial: 1000 monthly_after_24: 1000 one_off: 0 term_months: 12 roaming: Viewing within the EU included extras: 100+ channels; seven-day replay; two parallel streams magenta_eins_discount: 0 device_eligible: false

TV_SMART
name: MagentaTV Smart line_type: ott headline: MagentaTV with Netflix and Disney+ included data_gb: 0 speed: Not applicable monthly_initial: 0 monthly_after_24: 1100 one_off: 0 term_months: 24 roaming: Viewing within the EU included extras: 160+ HD channels; MagentaTV+ on-demand films and series; RTL+ Premium included; free for the first 6 months, then the standard rate; also bookable without a Telekom internet line at a flexible term; up to 3 parallel streams; Disney+ included on the SmartStream/MegaStream variants magenta_eins_discount: 500 device_eligible: false

TV_SPORT
name: MagentaSport line_type: ott headline: Live sport, including PENNY DEL ice hockey and MagentaSport events data_gb: 0 speed: Not applicable monthly_initial: 1495 monthly_after_24: 1495 one_off: 0 term_months: 12 roaming: Viewing within the EU included extras: 400+ live PENNY DEL ice hockey matches per season; ice hockey and field hockey World Championships; up to 300 days of live golf (PGA Tour, DP World Tour, Ryder Cup); two parallel streams magenta_eins_discount: 0 device_eligible: false

TV_DAZN
name: DAZN Unlimited via Telekom line_type: ott headline: Bundesliga conference, every Sunday match and the Champions League data_gb: 0 speed: Not applicable monthly_initial: 2900 monthly_after_24: 4499 one_off: 0 term_months: 12 roaming: Viewing within the EU included extras: Bundesliga conference and all Sunday matches; UEFA Champions League; promotional price for the first year, then the standard rate; booked as an add-on to an existing MagentaTV or Telekom account magenta_eins_discount: 0 device_eligible: false

TV_JOYNPLUS
name: Joyn+ by Telekom line_type: ott headline: Ad-light shows and series, early access before TV broadcast data_gb: 0 speed: Not applicable monthly_initial: 500 monthly_after_24: 699 one_off: 0 term_months: 12 roaming: Viewing within the EU included extras: Shows and series available before their TV broadcast; significantly fewer ad breaks; offline downloads; restart live TV from the beginning; exclusive Telekom-customer price for the first 12 months magenta_eins_discount: 0 device_eligible: false

Streaming and sport add-ons (from telekom.de)
Beyond the OTT tariffs above, MagentaTV subscribers can add specific streaming partners individually rather than upgrading the whole tariff: Disney+ (bundled on the SmartStream/MegaStream tiers, or bookable separately), Netflix, and RTL+ Premium. MagentaTV runs on up to three devices in parallel and is available on Telekom's MagentaTV One box, Apple TV 4K, streaming sticks (MagentaTV Stick, Fire TV Stick, Chromecast, Google TV Streamer), and directly inside Smart TV apps (Samsung, LG, Sony, etc.).
