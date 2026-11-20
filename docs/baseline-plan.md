# Baseline capture plan (2 weeks before go-live)

Goal: a real "before" number, so the "after" means something. Without it, any improvement claim is a guess.

## Rules
1. **Do not change how the shop answers enquiries during these 2 weeks.** Same phone, same WhatsApp
   Business app, same people. Only add logging.
2. Log **every** enquiry: WhatsApp, phone call, Google Maps call, Instagram/Facebook DM, walk-in that asks
   for a rate, website form. Repeat customers too.
3. Log the time the enquiry came in and the time someone first replied (message, call back, or spoke in
   person). Walk-ins served immediately: reply time = enquiry time.
4. Fill the outcome later when known: open / quoted / won (with invoice ₹) / lost.
5. 14 consecutive days, including at least one Sunday if the shop is open on Sundays.

## Two ways to log (pick one)
- **Phone:** open `https://<your-service>/staff/baseline` (login: staff password), tap Save after each
  enquiry. Download CSV any time from the same page.
- **Paper:** a ruled notebook at the counter with these columns, then Hussain types it into
  `docs/baseline_logbook.csv` and runs `stl baseline-import docs/baseline_logbook.csv`.

| # | Source (WA / call / walk-in / Insta / Google) | Date | Enquiry time | First reply time | Outcome | Quote ₹ | Invoice ₹ | Notes | Initials |
|---|---|---|---|---|---|---|---|---|---|

## What is computed from it (`metrics.baseline_summary`)
- Enquiries per day and by source
- First human reply time: median and p90, in minutes, counted from shop-open time
- % replied within 5 minutes; enquiries never replied
- Enquiry → sale conversion %, revenue from logged enquiries

## After go-live (same definitions)
The live system records the same fields automatically (first auto reply, first human reply via the staff
page, quote, won/lost). The public dashboard shows baseline vs live side by side. Compare after at least
4 weeks live; small numbers swing a lot, so report counts next to every percentage.

## Known biases
- Staff may reply faster just because they are logging (Hawthorne effect). Logging for 2 full weeks
  reduces this.
- Paper times are rounded; ask staff to write the minute, not "around 11".
- Festival weeks (Diwali, Ganpati) change demand; note them and avoid comparing a festival week to a
  normal one.
