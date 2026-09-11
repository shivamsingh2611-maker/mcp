# Required consents and pre-contractual information

Demo data. Each `## ID` block is one consent the customer must grant explicitly
before an order can be placed. `applies_to` is a comma-separated list of
line types (`mobile`, `fixed`, `ott`) or `all`.

## TKG54_PIB
label: Produktinformationsblatt and contract summary received
statute: TKG section 54
applies_to: all
mandatory: true
body: I confirm I have received and read the pre-contractual information and the contract summary for the products in this order, including price, minimum term, speeds and what changes after the minimum term.

## AGB
label: General terms and service description accepted
statute: AGB and Leistungsbeschreibung
applies_to: all
mandatory: true
body: I accept the Allgemeine Geschaeftsbedingungen and the Leistungsbeschreibung for the selected products.

## WIDERRUF
label: Right of withdrawal acknowledged
statute: BGB section 355
applies_to: all
mandatory: true
body: I have been informed that I may withdraw from this contract within 14 days without giving any reason. The period begins on the day I receive the goods, or on conclusion of the contract for services.

## CARD_MANDATE
label: Card payment authorisation
statute: PSD2 strong customer authentication
applies_to: all
mandatory: true
body: I authorise Telekom Deutschland GmbH to charge the recurring and one-off amounts of this order to the card I have tokenised, and I understand that strong customer authentication may be requested by my bank.

## FIXED_INSTALL
label: Installation and engineer appointment
statute: Not applicable
applies_to: fixed
mandatory: true
body: I understand that a technician appointment may be required at the installation address and that the service activation date depends on line availability.

## OTT_MINOR
label: Age confirmation for content services
statute: JMStV youth protection
applies_to: ott
mandatory: true
body: I confirm I am at least 18 years old and that age-restricted content will be protected by a PIN on my account.

## MARKETING
label: Marketing contact
statute: Optional
applies_to: all
mandatory: false
body: Telekom may contact me about offers and product news by email. I can withdraw this at any time.
