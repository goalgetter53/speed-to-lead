# SETUP — step by step (for Hussain)

Plain steps, in order. Every step is free. Where something might cost money, it says so.
Time needed: about 3–4 hours spread over a few days (Meta reviews take time).

Order: **A → B → C (start the 2-week baseline now) → D … J → K (go live after baseline)**.

---

## A. Get the code running on your laptop (15 min)
1. `git clone` the repo, `cd speed-to-lead`.
2. `make install` (creates `.venv`, installs everything).
3. `make check` → lint, types and tests must pass.
4. `make demo` → runs the fake-WhatsApp simulation. You should see all lines `[PASS]`.
5. Open `demo_output/dashboard_synthetic.html` in a browser to see what the dashboard will look like.

## B. Decide the WhatsApp number (important)
The WhatsApp Business **Platform** (Cloud API) and the WhatsApp Business **app** on the phone are different.

- **Option 1 (recommended, simplest): a new number.** Buy a new prepaid SIM (~₹100–200, the only cost in
  this whole setup; skip if you already have a spare number). Use it only for the API. Keep the shop's old
  WhatsApp number running as it is, and put the new number's `wa.me` link everywhere new.
- **Option 2: move the existing shop number.** A number already on the WhatsApp Business app must first be
  removed from the app (in the app: Settings → Account → Delete account) before it can be registered on the
  Cloud API. Chat history on the phone is lost and the father can no longer reply from the app. Do this only
  after the baseline (step C) is finished.
- **Option 3: "coexistence".** Since 2025 Meta lets some numbers stay on the WhatsApp Business app and the
  Cloud API at the same time, but onboarding goes through a Meta partner's "Embedded Signup" and is not
  available everywhere. Check with a partner before relying on it.

## C. Start the 2-week baseline NOW (before anything goes live)
Read `docs/baseline-plan.md`. Short version:
1. Print the table from `docs/baseline-plan.md` or keep a notebook at the counter.
2. For 14 days, write down every enquiry: source, time it came, time of first reply, outcome.
3. Do **not** change how the shop answers during these 2 weeks.
4. When the server is deployed (step H), staff can log on the phone at `/staff/baseline` instead of paper.
5. Paper entries: type them into `docs/baseline_logbook.csv` and run
   `.venv/bin/python -m speed_to_lead baseline-import docs/baseline_logbook.csv`.

## D. Meta Business account + app (30 min)
1. Go to **business.facebook.com** → create a Business portfolio "United Trader" (use the shop's real
   address; Meta may ask for business verification later — GST certificate or Udyam works well).
2. Go to **developers.facebook.com** → My Apps → Create app → type **Business** → connect it to the
   United Trader portfolio.
3. In the app, add the product **WhatsApp** → "API Setup". Meta gives you a test number and a temporary
   token. Send yourself a test message from that page to see it works.
4. **Add the real number:** WhatsApp Manager → Phone numbers → Add phone number → display name
   "United Trader" → verify with the SMS/voice code. The display name needs Meta approval (usually 1–2 days).
5. Copy these into your `.env` (copy `.env.example` to `.env` first):
   - `STL_WA_PHONE_NUMBER_ID` — WhatsApp → API Setup → "Phone number ID"
   - `STL_WA_BUSINESS_NUMBER` — the number as digits, e.g. `91XXXXXXXXXX`
   - `STL_WA_APP_SECRET` — App settings → Basic → App secret (Show)
   - `STL_GRAPH_VERSION` — the version shown in the API Setup sample (e.g. `v23.0`)

## E. Permanent access token (15 min)
The token on the API Setup page expires in 24 hours. Make a permanent one:
1. business.facebook.com → Settings → **Users → System users** → Add → name "stl-bot", role **Admin**.
2. "Assign assets": give it your **App** (full control), your **WhatsApp account** (full control), and
   your **Facebook Page** (full control, needed for lead ads).
3. "Generate new token" → choose your app → expiry **Never** → tick permissions:
   `whatsapp_business_messaging`, `whatsapp_business_management`, `leads_retrieval`,
   `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `business_management`.
4. Copy the token to `STL_WA_ACCESS_TOKEN` (and `STL_META_PAGE_TOKEN` if you want a separate one).
   Treat it like a password: never commit it, never paste it in chats.

## F. Supabase database (10 min, free)
1. supabase.com → New project → region **Mumbai (ap-south-1)** → strong DB password.
2. Project Settings → Database → Connection string → **Session pooler** URI (works on IPv4 hosts).
3. Put it in `STL_DATABASE_URL` (`postgresql://...`). Tables are created automatically on first start
   (`migrations/`), including row-level security so the public API keys can't read leads.
4. Note: free Supabase projects pause after a period of no activity; daily shop traffic keeps it awake.
   If it pauses, open the Supabase dashboard and click Restore.

## G. Telegram alerts for the owners (10 min, free)
1. In Telegram, open **@BotFather** → `/newbot` → name "United Trader Leads" → copy the token to
   `STL_TELEGRAM_BOT_TOKEN`.
2. Father, painter partner and you each open the bot and press **Start**.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser; each person's `chat.id` is listed.
   Put them in `STL_TELEGRAM_FATHER_CHAT`, `STL_TELEGRAM_PAINTER_CHAT`, `STL_TELEGRAM_HUSSAIN_CHAT`.
4. Optional WhatsApp alerts: put owner numbers in `STL_OWNER_*_WA`. They only work for free if that owner
   sends "hi" to the business number each morning (opens their own 24 h window).

## H. Deploy free (20 min)
**Option 1 — Render free web service (check their current free-tier terms):**
1. Push the repo to GitHub (goalgetter53). render.com → New → Web Service → pick the repo → it detects the
   `Dockerfile`. Instance type **Free**.
2. Add all `.env` values as Environment Variables. Set `STL_DRY_RUN=true` for now.
3. Set `STL_PUBLIC_BASE_URL` to the Render URL, `STL_STAFF_PASSWORD` and `STL_CRON_SECRET` to long random
   strings.
4. **Keep it awake:** free Render services sleep after ~15 min idle and take up to a minute to wake, which
   would break the 60-second promise. At cron-job.org (free) create a job every 5 minutes:
   `POST https://<your-service>/cron/tick` with header `X-Cron-Secret: <your secret>`. This also runs the
   SLA checks.
5. Open `https://<your-service>/healthz` → `{"ok": true, ...}`.

**Option 2 — Google Cloud Run:** generous free tier and fast cold starts, but needs a billing account
with a card on file. Same Docker image; set `STL_SLA_LOOP_SECONDS=0` and use the cron job above.

Free-tier limits change often; check the provider's current page before choosing.

## I. Connect the webhooks (15 min)
1. App dashboard → WhatsApp → **Configuration** → Webhook → Callback URL
   `https://<your-service>/webhooks/meta`, Verify token = the value you set in `STL_WA_VERIFY_TOKEN`
   (invent a long random string) → **Verify and save**. Then under "Webhook fields" subscribe to
   **messages**.
2. Every request is checked against your App Secret (`X-Hub-Signature-256`); wrong secret = 403 in logs.
3. Send a WhatsApp message to the business number from your own phone. With `STL_DRY_RUN=true` nothing is
   sent back, but the lead appears at `/staff`. Switch `STL_DRY_RUN=false` only when step K starts.

## J. Templates, lead ads, Google, Instagram
**Message templates (4 ready in `templates/whatsapp_templates.json`, English + Hindi):**
`ut_enquiry_received`, `ut_quote_ready`, `ut_enquiry_followup`, `ut_owner_lead_alert`.
- Submit in WhatsApp Manager → Message templates → Create (copy text + example values), or by API:
  `curl -X POST "https://graph.facebook.com/v23.0/<WABA_ID>/message_templates" -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '<one template object from the JSON>'`
- Approval usually takes minutes to a day. Meta may change the category (follow-ups can become MARKETING).
- **Cost warning:** templates are paid messages. They stay unused while `STL_ALLOW_PAID_TEMPLATES=false`.
  Pricing changed in 2026 (see `docs/adr/0001-free-only-whatsapp-design.md`); check Meta's rate card first.

**Facebook / Instagram lead forms (free webhook):**
1. App dashboard → add product **Webhooks** → choose **Page** → callback URL = same
   `https://<your-service>/webhooks/meta`, same verify token → subscribe to **leadgen**.
2. Subscribe your Page to the app:
   `curl -X POST "https://graph.facebook.com/v23.0/<PAGE_ID>/subscribed_apps?subscribed_fields=leadgen&access_token=<PAGE_ACCESS_TOKEN>"`
3. Business settings → Integrations → **Leads access** → allow your app.
4. In each lead form add a custom question "Can we contact you on WhatsApp?" (Yes/No). Use Meta's Lead Ads
   Testing Tool to send a test lead, look at the lead in `/staff`, and if the question's field name is not
   `whatsapp_opt_in`, set `STL_LEADFORM_OPTIN_FIELD` to the name shown.
5. Instagram lead ads arrive through the same Page webhook (`platform: ig`).

**Click-to-WhatsApp ads:** create them in Ads Manager with destination WhatsApp → choose the business number.
They are tracked automatically (`ctwa_ad`) and Meta gives a 72-hour free messaging window.

**Google Business Profile:** Google shut down its Business Messages chat in July 2024. Instead:
- Put the link `https://wa.me/91XXXXXXXXXX?text=Hi%20United%20Trader%20(ref:gbp)` wherever the profile
  allows a link (website, booking/appointment link, or a Google post). If your profile shows a WhatsApp/chat
  option under Edit profile → Contact, use the same link there.
- Calls from Google Maps: staff log them at `/staff/new` → source "Google Maps call".

**Instagram / Facebook DMs:** put the WhatsApp link with `(ref:ig)` / `(ref:fb)` in the bio and in Meta
Business Suite → Inbox → Automations → Instant reply ("For fastest rates, message us on WhatsApp: <link>").
DMs that don't move to WhatsApp: log at `/staff/new`.

**Counter QR code:** make a QR of `https://wa.me/91XXXXXXXXXX?text=Hi%20United%20Trader%20(ref:qr)` and
stick it at the counter and on delivery bills.

**Website form:** paste `docs/website_form_snippet.html`, set `STL_FORM_ALLOWED_ORIGINS`.

## K. Go live (after 14 days of baseline)
1. Fill `STL_CATALOGUE_URL` (Google Drive PDF of the price list is fine), check shop hours and
   `STL_SHOP_LAT/LON` (exact location from Google Maps).
2. Set `STL_DRY_RUN=false`. Send yourself a test WhatsApp: you should get the reply within seconds and a
   Telegram alert should reach the owner.
3. Give father and the painter partner the Hindi quick guide (`docs/SETUP_HI.md`) and the staff link +
   password. Show the ✅ "I replied" button — the "after" numbers depend on staff pressing it.
4. Weekly: `make dashboard` (or open `/dashboard`) and publish `site/index.html` (GitHub Pages). It contains
   only totals, never names or numbers.

## Privacy and rules (India DPDP Act 2023 + WhatsApp policy)
- The system only replies to people who messaged first, or who ticked a consent box (website form, lead
  form question, or staff-recorded verbal consent for walk-ins). The consent source and time are stored.
- STOP / बंद / थांबवा stops all automatic messages instantly; START resumes. Opt-outs are never messaged.
- Data minimisation: we keep phone, name, enquiry text and outcome — nothing else.
- Erasure request ("delete my data"): `python -m speed_to_lead forget +91XXXXXXXXXX`.
- The DPDP Rules were notified in Nov 2025 with phased compliance dates; for a small shop the practical
  duties are: say why you collect the number, use it only for the enquiry, honour deletion requests, keep it
  secure. This is not legal advice.
- No marketing broadcasts from this system. Promotional messages need separate opt-in and paid templates.
