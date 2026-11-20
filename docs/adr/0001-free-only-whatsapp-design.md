# ADR 0001: Free-only WhatsApp design (customer-initiated first, Telegram for owners)

Status: accepted, 2026-11-20

## Context
The shop has no budget for messaging. On the WhatsApp Business Platform, the business can send free-form
("service") messages only inside the 24-hour window that opens when the customer messages first. Messages
outside the window need approved templates, which are charged per message.

Pricing moved during 2026. Meta's pricing page (as fetched on 2026-11-20) still says non-template messages
are free and utility templates inside an open window are free. A Meta partner (AiSensy) reports that from
1 Oct 2026 service messages beyond 1,000 per phone number per month are billed (about ₹0.145 each in India),
and utility templates are billed even inside the window. Click-to-WhatsApp ad conversations keep a 72-hour
free window. **Check Meta's current rate card before go-live.**

## Decision
1. Automate only inside a window the customer opened: first reply, two qualifying questions, two follow-ups
   (2 h and 22 h, shop hours only). After 24 h the system stops and tells a human to call.
2. Push every channel towards customer-initiated chats: `wa.me` links with a `(ref:xx)` tag on Google
   Business Profile, Instagram, website thank-you page, and a QR code at the counter. The tag gives free
   source attribution.
3. Meta lead-form leads have no window, so the default action is a "CALL NOW" alert to the owner (calls are
   free). Templates exist and are wired (`STL_ALLOW_PAID_TEMPLATES=true`) but are off.
4. A monthly counter pauses automation at `STL_SERVICE_MSG_MONTHLY_CAP` (default 950) so the shop never
   crosses the free allowance without knowing.
5. Owner alerts go to Telegram (free, unlimited). WhatsApp alerts to an owner are sent only if that owner
   messaged the business number in the last 24 h (a morning "hi" keeps it open).

## Consequences
- Lead-ad leads depend on a human calling quickly; the SLA timer and escalation cover that.
- If Meta changes pricing again, only the cap and the template switch need to change.
