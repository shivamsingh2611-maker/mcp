# Telekom device catalogue

Demo data. Edit this file and restart the server.
`monthly_by_tariff` maps a tariff ID to the monthly device instalment in euro cents.
A tariff missing from that map cannot be combined with the device.

The lineup below was extended from Telekom's real "Handys ohne Vertrag" device
list (telekom.de) to cover flagship, mid-range, budget and refurbished phones
across every brand Telekom currently sells, plus the newly added MagentaMobil
XS tariff. Per-tariff instalments follow this demo's own pricing convention
(a cheaper tariff pays a higher device instalment, a pricier tariff a lower
one) rather than reproducing Telekom's live financing calculator — see the
README for why this stays illustrative. Prose outside the `key: value` lines
is ignored by the parser but still readable by the model via the
`telekom://catalogue/devices` resource.

## IP17P_256
name: iPhone 17 Pro
brand: Apple
storage: 256 GB
colour: Natural Titanium
one_off: 4900
monthly_by_tariff: MM_XS=3995, MM_S=3495, MM_M=2495, MM_L=1995, MM_XL=1495
stock: in_stock
highlights: A19 Pro chip; 6.3 inch ProMotion display; 48 MP fusion camera; eSIM only

## IP17_128
name: iPhone 17
brand: Apple
storage: 128 GB
colour: Lavender
one_off: 100
monthly_by_tariff: MM_XS=2895, MM_S=2495, MM_M=1795, MM_L=1295, MM_XL=995
stock: in_stock
highlights: A19 chip; 6.1 inch display; 48 MP main camera; eSIM only

## SGS26U_256
name: Galaxy S26 Ultra
brand: Samsung
storage: 256 GB
colour: Titanium Black
one_off: 4900
monthly_by_tariff: MM_XS=3795, MM_S=3295, MM_M=2195, MM_L=1795, MM_XL=1295
stock: in_stock
highlights: Snapdragon 8 Elite; 6.9 inch QHD+ display; 200 MP camera; S Pen included; first Galaxy with a Privacy Display

## SGS26_128
name: Galaxy S26
brand: Samsung
storage: 128 GB
colour: Mint
one_off: 100
monthly_by_tariff: MM_XS=2495, MM_S=2195, MM_M=1595, MM_L=1095, MM_XL=795
stock: in_stock
highlights: Snapdragon 8 Elite; 6.2 inch display; 50 MP triple camera

## PIX10_128
name: Pixel 10
brand: Google
storage: 128 GB
colour: Obsidian
one_off: 100
monthly_by_tariff: MM_XS=2295, MM_S=1995, MM_M=1395, MM_L=995, MM_XL=695
stock: backorder
highlights: Tensor G5; 6.3 inch Actua display; Gemini Nano on device

## SIMONLY
name: No device
brand: Telekom
storage: Not applicable
colour: Not applicable
one_off: 0
monthly_by_tariff: MM_XS=0, MM_S=0, MM_M=0, MM_L=0, MM_XL=0
stock: in_stock
highlights: SIM only; keep your current handset; eSIM or physical SIM

## IP18P_256
name: iPhone 18 Pro
brand: Apple
storage: 256 GB
colour: Burgunder
one_off: 9900
monthly_by_tariff: MM_XS=5595, MM_S=4895, MM_M=3495, MM_L=2795, MM_XL=2095
stock: preorder
highlights: Apple's newest Pro-series chip; 6.3 inch ProMotion display; 48 MP fusion camera; eSIM only; also available in 512 GB, 1 TB and 2 TB; limited-time 50 euro Telekom trade-in deal

## IP18PM_256
name: iPhone 18 Pro Max
brand: Apple
storage: 256 GB
colour: Silber
one_off: 9900
monthly_by_tariff: MM_XS=5995, MM_S=5195, MM_M=3595, MM_L=2895, MM_XL=2195
stock: preorder
highlights: Largest display in the 18 Pro line; 48 MP fusion camera; eSIM only; also available in 512 GB, 1 TB and 2 TB

## IPAIR_256
name: iPhone Air
brand: Apple
storage: 256 GB
colour: Space Black
one_off: 100
monthly_by_tariff: MM_XS=3995, MM_S=3495, MM_M=2495, MM_L=1995, MM_XL=1495
stock: in_stock
highlights: Apple's thinnest iPhone; eSIM only; also available in 512 GB and 1 TB

## IP17PM_256
name: iPhone 17 Pro Max
brand: Apple
storage: 256 GB
colour: Natural Titanium
one_off: 9900
monthly_by_tariff: MM_XS=5095, MM_S=4495, MM_M=3195, MM_L=2595, MM_XL=1995
stock: in_stock
highlights: A19 Pro chip; largest Pro display and battery; 48 MP fusion camera; eSIM only; also available in 512 GB, 1 TB and 2 TB

## IP16E_128
name: iPhone 16e
brand: Apple
storage: 128 GB
colour: Black
one_off: 100
monthly_by_tariff: MM_XS=2495, MM_S=2195, MM_M=1595, MM_L=1295, MM_XL=995
stock: in_stock
highlights: Entry-level current-generation iPhone; A18 chip; eSIM only; also available in 512 GB

## IP13_REF_128
name: iPhone 13 (Erneuert Basic)
brand: Apple
storage: 128 GB
colour: Midnight
one_off: 0
monthly_by_tariff: MM_XS=1895, MM_S=1595, MM_M=1195, MM_L=995, MM_XL=795
stock: in_stock
highlights: Telekom-certified refurbished device; 24-month warranty; budget option for customers who don't need the newest hardware

## PIX11P_256
name: Pixel 11 Pro
brand: Google
storage: 256 GB
colour: Obsidian
one_off: 4900
monthly_by_tariff: MM_XS=4895, MM_S=4295, MM_M=3095, MM_L=2495, MM_XL=1895
stock: in_stock
highlights: Tensor G6; Google AI Pro and premium services included; up to 300 euro trade-in bonus when selling an eligible used phone

## PIX11_128
name: Pixel 11
brand: Google
storage: 128 GB
colour: Porcelain
one_off: 4900
monthly_by_tariff: MM_XS=3995, MM_S=3495, MM_M=2495, MM_L=1995, MM_XL=1495
stock: in_stock
highlights: Tensor G6; premium Google AI benefits included; up to 200 euro trade-in bonus

## PIX10A_128
name: Pixel 10a
brand: Google
storage: 128 GB
colour: Aloe
one_off: 0
monthly_by_tariff: MM_XS=2095, MM_S=1795, MM_M=1295, MM_L=1095, MM_XL=795
stock: in_stock
highlights: Budget Pixel with Tensor G5; premium-vorteile bundle included; cheapest current Pixel Telekom sells

## SGZF8_512
name: Galaxy Z Fold8
brand: Samsung
storage: 512 GB
colour: Titanium Gray
one_off: 19900
monthly_by_tariff: MM_XS=6995, MM_S=6195, MM_M=4495, MM_L=3595, MM_XL=2695
stock: in_stock
highlights: Book-style foldable; large inner display for multitasking; 6 months of Google AI Pro included; also available as the higher-spec Z Fold8 Ultra

## SGZFL8_256
name: Galaxy Z Flip8
brand: Samsung
storage: 256 GB
colour: Blue
one_off: 9900
monthly_by_tariff: MM_XS=4895, MM_S=4295, MM_M=3095, MM_L=2495, MM_XL=1895
stock: in_stock
highlights: Compact clamshell foldable; cover-screen multitasking; 6 months of Google AI Pro included

## SGA57_128
name: Galaxy A57 5G
brand: Samsung
storage: 128 GB
colour: Awesome Navy
one_off: 100
monthly_by_tariff: MM_XS=2395, MM_S=2095, MM_M=1495, MM_L=1195, MM_XL=895
stock: in_stock
highlights: Mid-range 5G device; also available in 256 GB; up to 100 euro trade-in bonus

## XIA17TP_512
name: Xiaomi 17T Pro
brand: Xiaomi
storage: 512 GB
colour: Black
one_off: 100
monthly_by_tariff: MM_XS=3995, MM_S=3495, MM_M=2495, MM_L=1995, MM_XL=1495
stock: in_stock
highlights: Flagship-tier Xiaomi at a mid-range price; up to 100 euro trade-in bonus

## MOTRAZR_512
name: motorola razr fold FIFA Edition
brand: motorola
storage: 512 GB
colour: FIFA Edition
one_off: 19900
monthly_by_tariff: MM_XS=8995, MM_S=7895, MM_M=5595, MM_L=4495, MM_XL=3395
stock: in_stock
highlights: Clamshell foldable, special FIFA-branded edition; compact folded footprint

## NP3_256
name: Nothing Phone (3)
brand: Nothing
storage: 256 GB
colour: White
one_off: 100
monthly_by_tariff: MM_XS=2995, MM_S=2595, MM_M=1895, MM_L=1495, MM_XL=1095
stock: in_stock
highlights: Distinctive transparent-back design with Glyph lighting; mid-range price point

### Protecting and financing a device (from telekom.de)

Every phone above can be paired with optional device protection at checkout:
- **Unfallschutz** (accident protection): roughly 13 euro/month.
- **Unfall- und Diebstahlschutz** (accident and theft protection, most
  popular): roughly 15 euro/month.

**Handyankauf (trade-in).** Selling a used phone, smartwatch or tablet back
to Telekom offsets the cost of a new device; several models above carry an
extra "Ankaufsbonus" (trade-in bonus) on top of the normal trade-in value —
see each device's highlights.

**Delivery.** Free shipping, and returns are accepted within 14 days of
delivery, matching the order flow's 14-day withdrawal period in
`consents.md`.
