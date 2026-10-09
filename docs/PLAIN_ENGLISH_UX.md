# Locuvi writing guide — plain British English

Locuvi is one person's GP locum admin tool, not a product aimed at accountants or developers. The owner should understand every screen immediately without looking up terminology.

## Voice
- Warm, calm, professional British English (en-GB). No sales language or robot-like messages.
- Short sentences. Use "you", "your" and familiar verbs: **add**, **check**, **send**, **save**, **record**, **download**.
- Buttons should say what they actually do. A destructive or final action deserves a plain warning about its consequences.
- Keep headings about **the user's task** rather than the internal feature or database object.
- Prefer: "Still owed to you", "Dates worked", "Save a copy to Nextcloud".
- Avoid where possible: "reconciliation", "artefact", "preflight", "immutable", "persist", "sync", "ledger", "eligibility flag", "metadata".
- Give a next step in errors. Say how to resolve the problem.

## Terms we must retain accurately
These are terms in official processes; explain them **the first time they matter**, rather than replacing them with something legally misleading.
- **Invoice**: a numbered official bill. **Issue** allocates a number and freezes the original PDF; a draft is editable.
- **Credit note**: an official correction that leaves the original issued invoice in place; do not call it "delete invoice".
- **NHS pensionable pay**: the official pension calculation base, normally 90% of eligible basic fees. An inline explanation can say "amount used to calculate NHS pension".
- **Employer contribution**: the practice's contribution; distinct from **your own pension contribution**.
- **Form A and Form B**, **PCSE**, **GMC**, **VAT**: official labels; explain their function alongside them.
- **Cash received versus invoiced income**: different reporting views; never use "earned" as an ambiguous substitute.
- **Nextcloud PDF copy** is not a full backup of the Locuvi database; always preserve that warning.

## Key workflow labels
| Before | Prefer | Why |
| --- | --- | --- |
| Work lines | Work to charge for | Describes the action |
| Pensionable pay ({fraction}, explanatory) | Amount used to calculate pension ({fraction}) | Explains the sum |
| Status: overdue | Payment is late | Describes the actual problem |
| Nextcloud backup pending | Waiting to save a copy to Nextcloud | A PDF copy isn't a full backup |
| Split by month | Make a separate invoice for each month | States the result |
| Worksheet | Download figures | Says what the button delivers |
| Import PCSE | Import PCSE figures | Makes the action concrete |
| Remittance | Payment advice | Recognisable wording |
| Credit notes | Invoice corrections (credit notes) | Explains the official term |
| Copy token | Copy connection key | Avoids unexplained jargon |

## Safety and accuracy rules
1. Do **not** simplify away legally meaningful distinctions, deadlines, amount calculations, consent or permissions.
2. Copy-only changes must not change backend logic, invoice PDF values, tax calculations or pension rules.
3. Preserve every `{parameter}` placeholder, including its exact name; do not remove or duplicate parameters.
4. All UI messages belong in `frontend/src/i18n/en.ts`. Do not hard-code new text into React components.
5. Keep the six-language translation structure. After editing English, existing DE/KO/FR/ES/PT wording must be reviewed for changed meaning — other languages can still display old explanations.
6. Test on a narrow phone view: especially long confirmations, invoice buttons and multi-line pension explanations.
7. Prefer specific success messages ("Invoice saved", "Payment recorded") rather than "Success".
8. Tell the truth about automation: "suggested" isn't "confirmed"; "uploaded" isn't "verified"; "marked submitted" isn't proof of receipt.

## Review checklist
- Can a GP understand this label at first glance?
- Is it clear what will happen when they click?
- Is the wording correct if the user hasn't set up email, Nextcloud or AI?
- Is it clear whose money is being shown and which date governs it?
- Is a payment actually received, or just invoiced?
- Does the interface distinguish practice contributions from the GP's own contributions?
- Is the language factual even when something fails?

## Related work
The English copy overhaul is on `review/plain-english-ux-20261009`, kept separate from the draft five-language PR `review/i18n-native-polish-20261009`. After the English wording is accepted, rebase the translations and review strings whose meaning changed. Do not merge conflicting catalogues blindly.
