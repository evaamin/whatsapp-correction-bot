# WhatsApp Correction & Follow-up Bot (MVP)

Replaces a manual Excel-based correction-tracking workflow. A coordinator
sends a correction request naming a center; the bot forwards it, tracks its
status, classifies the center's reply as a plain acknowledgement vs. a
substantive response, and automatically nudges centers that go quiet.

## How it works

1. **Coordinator → bot.** The coordinator sends a WhatsApp message shaped
   like `clinicA: please fix the intake form field`. The bot creates a
   tracking record (`status = sent`) and forwards the request text to
   `clinicA`'s WhatsApp thread.
2. **Center replies.** The bot classifies the reply using the Claude API —
   *acknowledgement* (e.g. "ok, will check") or *substantive* (actually
   addresses the correction). Acknowledgements move the record to
   `acknowledged`; substantive replies move it to `resolved` and log the
   response text.
3. **Bot → coordinator.** A short status update is posted back to the
   coordinator's chat after every reply.
4. **Follow-up scheduler.** A background job checks periodically for
   requests that have gone quiet longer than `FOLLOWUP_INTERVAL_MINUTES`. It
   sends an automatic nudge to the center and increments a follow-up
   counter. After `MAX_FOLLOWUPS` nudges with no response, the request
   flips to `overdue` instead of nudging forever.

Tracked per request: id, center, request text, sent timestamp, status
(`sent` / `acknowledged` / `resolved` / `overdue`), follow-up count,
response text, resolved timestamp.

## Project layout

```
app/
  config.py         # loads .env + centers.json — the only place credentials are read
  models.py         # Status constants + CorrectionRequest dataclass
  db.py             # SQLite repository (data/tracking.db)
  classifier.py      # Claude API classification, with a heuristic fallback
  messaging.py       # Twilio or Meta WhatsApp Cloud API wrapper (prints instead of sending if unconfigured)
  state_machine.py   # core tracking logic — used by the webhook, scheduler, and CLI
  scheduler.py        # APScheduler background job for follow-up nudges
  main.py             # FastAPI app + Twilio and Meta webhooks
cli_dry_run.py         # simulate the whole flow locally, no credentials needed
tests/                 # pytest suite (runs in heuristic/dry-run mode, no credentials needed)
centers.example.json   # template for centers.json (name -> WhatsApp number)
.env.example            # template for .env — every credential is a placeholder here
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
cp centers.example.json centers.json
```

Edit `centers.json` to map each center's name to its WhatsApp number:

```json
{ "clinicA": "whatsapp:+15551230001", "clinicB": "whatsapp:+15551230002" }
```

### Where to put real credentials

Everything lives in `.env` (gitignored, never committed). Set
`WHATSAPP_PROVIDER` to `twilio` or `meta` depending on which one you're
using, then fill in that section:

- **Twilio** — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
  `TWILIO_WHATSAPP_NUMBER` from the
  [Twilio Console](https://console.twilio.com); `TWILIO_WHATSAPP_NUMBER`
  must be your WhatsApp-enabled Twilio number. `TWILIO_API_KEY_SID` /
  `TWILIO_API_KEY_SECRET` are optional, only if you provision a separate API
  key instead of using the main auth token.
- **Meta WhatsApp Cloud API** — `WHATSAPP_ACCESS_TOKEN` and
  `WHATSAPP_PHONE_NUMBER_ID` from your Meta App Dashboard's WhatsApp → API
  Setup page. `WHATSAPP_VERIFY_TOKEN` is any string you choose; enter the
  same value in the dashboard's webhook Configuration page.
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com).
  Requires billing credit on the account — the free trial credit is small
  but classification at this volume costs a fraction of a cent per call.
- `COORDINATOR_WHATSAPP_NUMBER` — the number the coordinator sends requests
  from. Any inbound message from a different number is treated as a center
  reply.

Until real credentials are set, the app runs entirely in dry-run mode (see
below) — no code changes needed.

## Running it for real

```bash
uvicorn app.main:app --reload
```

The follow-up scheduler starts automatically with the app (checks every
`FOLLOWUP_CHECK_INTERVAL_SECONDS`, default 5 minutes). Point your provider's
webhook at whichever route matches `WHATSAPP_PROVIDER`:

- **Twilio** — set the WhatsApp number's "when a message comes in" webhook
  to `POST https://<your-host>/webhook/whatsapp`.
- **Meta** — in the App Dashboard's Configuration page, set the callback
  URL to `https://<your-host>/webhook/whatsapp/meta` and the verify token to
  match `WHATSAPP_VERIFY_TOKEN`. Meta calls `GET` on that same URL once to
  confirm you control it.

`<your-host>` needs to be a real public HTTPS address — for local
development, a tunnel like `ngrok http 8000` works and gives you one.

### Going from dev/test to real production traffic

- **Recipient limit.** A Meta *test* number (the free one from API Setup)
  can only message up to 5 phone numbers you've manually added as test
  recipients — fine for a pilot, not for a real center list. To lift that
  limit you need a verified WhatsApp Business Profile through Meta, which
  Twilio's onboarding flow can also walk you through if you switch
  providers. This takes real setup time; budget for it separately from
  writing the addresses down.
- **The 24-hour session window.** WhatsApp only allows free-form
  business-initiated messages (like the "New correction request" push) to a
  recipient who has messaged your number within the last 24 hours.
  Otherwise the send fails with a re-engagement error. In production this
  usually means getting an approved message template for the initial
  outreach, or having each center send one message to open the window
  before you start routing requests to them.
- **Delivery failures degrade gracefully.** `app/messaging.py` logs (not
  raises) on a failed send — one center's delivery failure won't crash a
  request for every other center, but it's worth watching logs for
  `Failed to send WhatsApp message` if replies seem to be going missing.

Inspection routes: `GET /health`, `GET /requests` (JSON dump of all tracked
requests).

## Local dry-run / testing (no credentials needed)

`cli_dry_run.py` calls the exact same state-machine functions the webhook
uses, so it exercises the real request → reply → classify → follow-up logic
— just without Twilio or a live Claude API call:

- No `ANTHROPIC_API_KEY` set → replies are classified with a keyword
  heuristic (`app/classifier.py`) instead of the Claude API.
- No Twilio credentials set → outbound messages are printed to the console
  instead of sent.

```bash
python cli_dry_run.py centers                     # list configured centers
python cli_dry_run.py send clinicA "Please fix the intake form field"
python cli_dry_run.py reply clinicA "ok, will check"                     # -> acknowledged
python cli_dry_run.py reply clinicA "Fixed, redeployed the form"          # -> resolved
python cli_dry_run.py list                          # table of all tracked requests
python cli_dry_run.py export-csv out.csv             # dump the tracking log to CSV

# Test the follow-up escalation without waiting FOLLOWUP_INTERVAL_MINUTES:
python cli_dry_run.py send clinicB "Check the referral form"
python cli_dry_run.py age 2 <minutes>                # backdate request #2's last activity
python cli_dry_run.py check-followups                # runs the same logic the scheduler uses
```

Run `age` + `check-followups` repeatedly to watch a request go
`sent → (nudge, count=1) → (nudge, count=2) → overdue` (with the default
`MAX_FOLLOWUPS=3`).

## Storage

Tracking data lives in a local SQLite file (`data/tracking.db` by default —
configurable via `DB_PATH`). It's plain SQLite, so it's easy to inspect
directly:

```bash
sqlite3 data/tracking.db "select * from requests;"
```

`app/db.py` is the single module every other file goes through for storage
— no raw SQL anywhere else — and includes an `export_csv()` helper, so
swapping SQLite for a shared sheet or another database later means changing
one file, not the whole codebase.

## Tests

```bash
pytest tests/ -v
```

The test suite points at a scratch SQLite DB and scratch `centers.json` per
test (see `tests/conftest.py`) and never touches real credentials — it runs
the same heuristic/dry-run path as `cli_dry_run.py`.

## Defaults chosen (not specified in the original ask)

- **Web framework:** FastAPI, run with `uvicorn`.
- **Storage:** SQLite (over CSV) — same "just a file, easy to inspect"
  property, but with actual query/filter support the follow-up scheduler
  needs, and no risk of concurrent-write corruption between the webhook and
  the scheduler. `export_csv()` is included for anyone who wants a flat
  file to open in Excel/Sheets.
- **Scheduler:** APScheduler `BackgroundScheduler`, running in-process with
  the FastAPI app.
- **Center routing:** a `centers.json` file mapping center name → WhatsApp
  number, and a coordinator message format of `<center_name>: <text>`. This
  wasn't specified in the request; swap in whatever addressing scheme fits
  your center list (a DB table, a lookup service, etc.) by editing
  `app/config.py`'s `load_centers()`.
- **Classification model:** defaults to `claude-haiku-4-5` per
  `ANTHROPIC_MODEL` in `.env.example` — this is a small, cheap classification
  task (ack vs. substantive) and doesn't need a larger model. Swap to
  `claude-opus-5` if classification accuracy on ambiguous replies becomes
  an issue in practice.
