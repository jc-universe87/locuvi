# Locuvi — AI and Agentic Capabilities

Owner specification, 8 October 2026. Source of truth for the assistant phases in
[`docs/ROADMAP.md`](../ROADMAP.md) (Part 4).

## 1. General philosophy
Locuvi should be a conventional, reliable GP locum management application with an optional
AI-powered administrative assistant.

The AI should not replace the core application. Its role is to reduce repetitive administrative
work, identify omissions, analyse information from different sources, and proactively suggest or
prepare actions.

**Core principle: the application manages the records; the AI helps manage the work.**

All invoice calculations, pension calculations, deadlines and financial records must remain
deterministic, testable and auditable. AI must not be required for normal application functionality.

## 2. Planned AI capabilities

### A. Intelligent locum session capture
The AI should be able to:
- Read booking confirmation emails or uploaded documents.
- Extract practice names, dates, times, session numbers and agreed fees.
- Recognise changes or cancellations.
- Identify potential duplicate or conflicting bookings.
- Suggest new locum entries without requiring manual transcription.
- Ask for confirmation when information is incomplete or ambiguous.

*Example:* a practice sends an email confirming three sessions at £600 each. The AI identifies the
sessions and prepares the entries for approval.

### B. Invoice preparation assistant
The AI should:
- Identify completed but uninvoiced sessions.
- Suggest which sessions should be invoiced together.
- Prepare invoice drafts using confirmed session records.
- Detect missing or inconsistent rates.
- Prepare invoice emails addressed to the relevant practice.
- Recognise practice-specific invoicing requirements from saved instructions or correspondence.

Actual invoice numbers, amounts and PDF documents must be produced by the application's
deterministic invoice engine.

*Example:* "Prepare all outstanding invoices for September." The AI reviews the sessions and
generates drafts for approval.

### C. NHS pension administration assistant
When the Form A/B module is implemented, the AI should:
- Identify locum work without corresponding pension documentation.
- Track outstanding Form A approvals.
- Identify missing monthly Form B submissions.
- Highlight approaching pension deadlines.
- Compare expected contributions with imported PCSE records.
- Investigate discrepancies between invoices, payments and pension documentation.
- Prepare a prioritised list of outstanding actions.

The AI must not invent submission confirmations or assume that an uploaded form was accepted.

*Example:* "Check whether all my NHS pension contributions since April have been accounted for."
The AI reconciles the available records and reports outstanding or unverified items.

### D. Intelligent payment reconciliation
The AI should help match invoices with payments using imported bank transaction records or
statements:
- Match payments despite inconsistent references.
- Recognise combined payments covering several invoices.
- Identify partial payments or unexpected deductions.
- Flag unpaid or overdue invoices.
- Suggest explanations for discrepancies.
- Prepare payment reminder drafts.

No access to bank accounts is required initially. CSV statement imports are sufficient for an
initial implementation.

### E. Proactive administrative monitoring
One of the most valuable agentic capabilities. The assistant should periodically examine Locuvi's
records and identify work requiring attention, such as:
- Completed but uninvoiced sessions.
- Invoices approaching or exceeding payment deadlines.
- Pension documentation that remains incomplete.
- Missing payment confirmations.
- Duplicate or inconsistent records.
- Tasks that require follow-up.

Rather than requiring the user to ask repeatedly, Locuvi should present relevant findings through
a simple dashboard.

*Example notification:* "Two sessions have not been invoiced. One invoice is overdue, and one
Form A approval still needs verification."

Monitoring and deadline detection should primarily use deterministic rules. AI should investigate
and explain findings when useful.

### F. Context-aware correspondence
The AI should be able to:
- Draft invoice emails.
- Draft polite payment reminders.
- Prepare requests for missing pension documentation.
- Incorporate existing correspondence where permission has been granted.
- Adapt the tone to the situation.
- Suggest when another follow-up may be appropriate.

Emails must require user approval before sending.

### G. Financial and administrative analysis
The AI should support natural-language queries such as:
- "How much did I earn last month?"
- "Which practices still owe me money?"
- "How much income is outstanding this tax year?"
- "Which locum sessions have missing documentation?"
- "Prepare a summary for my accountant."
- "Why doesn't this payment match my invoice?"

The underlying figures must come from structured application records rather than AI-generated
estimates.

## 3. Agentic workflow
The eventual assistant should be capable of executing multi-step administrative investigations.
For example, user request: "Check all outstanding administrative work."
1. Retrieve the current session, invoice, payment and pension records.
2. Run deterministic validation and reconciliation checks.
3. Identify discrepancies or outstanding items.
4. Examine relevant authorised documents or correspondence when necessary.
5. Explain findings and distinguish confirmed facts from assumptions.
6. Prioritise actions by urgency.
7. Prepare appropriate drafts or corrections.
8. Request user approval before making consequential changes.

This is preferable to a generic chatbot with no direct access to Locuvi's actual functions.

## 4. Technical architecture
AI should be implemented as an independent, optional module:
- Provider-agnostic LLM interface.
- Support for cloud AI models and potentially local models.
- Tool-calling architecture exposing controlled application functions.
- Read-only operations permitted for routine analysis.
- Write operations subject to validation and appropriate approval.
- Structured outputs validated by backend schemas.
- Background administrative checks using a conventional scheduler.
- Audit log of AI proposals, tool executions and accepted changes.
- No dependency on AI for invoice generation or pension calculations.

Potential tools: `list_sessions`, `find_uninvoiced_sessions`, `get_invoice`,
`create_invoice_draft`, `list_outstanding_invoices`, `compare_payments`,
`audit_pension_records`, `read_authorised_document`, `draft_followup_email`,
`generate_financial_summary`.

These should operate through the application's existing service layer and permissions, not
through direct unrestricted database access.

The system should eventually support integration with **Bevro**, allowing Locuvi's administrative
functions to be used by external authorised agents.

## 5. Privacy and safety
Locuvi manages personal financial and professional records. Therefore:
- AI functionality must be explicitly enabled.
- Only the minimum necessary information should be shared with an AI provider.
- Bank credentials, WebDAV passwords and other secrets must never be sent to an LLM.
- Patient-identifiable information must not be processed.
- External integrations should use narrowly scoped permissions.
- Financial calculations must never rely on an LLM.
- AI must not autonomously submit pension forms, transfer funds, alter bank details or send
  correspondence.
- Issued invoices must remain immutable.
- AI suggestions must be clearly distinguished from confirmed information.
- Users must be able to review and reject proposed changes.
- A complete audit trail should be maintained for AI-assisted actions.

## 6. Implementation roadmap (owner's phases)
- **Phase 1 — No AI required.** Reliable invoicing foundation: structured session data, invoice
  generation, persistent records, Nextcloud/WebDAV storage. Backend service interfaces designed
  so future AI tools can reuse them.
- **Phase 2 — AI invoice assistant.** Extract session information from emails and documents;
  identify uninvoiced sessions; prepare invoice drafts; detect incomplete information; draft
  accompanying emails. All external communication requires confirmation.
- **Phase 3 — Administrative agent.** Proactive administrative checks; payment reconciliation
  assistance; pension Form A/B auditing; context-aware follow-up suggestions; natural-language
  questions over Locuvi's records.
- **Phase 4 — Extended agent integration.** Scheduled multi-step administrative reviews; email and
  calendar connectors; more advanced document processing; Bevro provider integration; optional
  local AI models; controlled execution of approved workflows.

## 7. Final design objective
Locuvi should eventually function as a personal GP locum administrative assistant. The goal is not
to make every feature AI-powered; it is to minimise time spent on invoicing, payment chasing,
pension paperwork and record reconciliation. Ideally, the user only verifies that their locum
sessions are correctly recorded, reviews proposed actions and approves them. The AI handles the
administrative investigation and preparation; the user remains in control of decisions and
submissions.
