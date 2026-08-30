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

## Something broken, or want a change?

Use this repo's **Issues** tab (top of the GitHub page) — open a new issue
describing what's not working or what you'd like added. That's the record
of everything to fix or build next; no need to reach out separately. This
repo is private, so you'll need to be added as a collaborator first (ask
whoever set this up for you).

## Setup walkthrough (deploying this for real)

**If you have [Claude Code](https://claude.com/claude-code):** open this
folder in it and just ask it to help you set the bot up. It reads
`CLAUDE.md` automatically and will walk you through everything below
interactively — filling in `.env`, deploying, registering the webhook,
troubleshooting — instead of you following each step by hand.

This section assumes you already have access to a WhatsApp Business
account through Meta (an App Dashboard with WhatsApp added, an access
token, and a Phone Number ID) and just need to get this bot running against
it. Do the steps in this order — some later steps need values from earlier
ones.

### 1. Get the code running locally

```bash
git clone https://github.com/evaamin/whatsapp-correction-bot.git
cd whatsapp-correction-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
cp centers.example.json centers.json
```

Verify it works before touching any credentials:

```bash
pytest tests/ -v          # should show 7 passed
python cli_dry_run.py centers
```

### 2. Deploy to a permanent public host

WhatsApp needs a real, always-on HTTPS URL to send messages to — it can't
call your laptop. Two options, depending on whether you'd rather pay a
small monthly fee for convenience or spend more setup time for $0
recurring cost.

#### Option A: Render (easiest, ~$5–7/month)

Connect your GitHub repo, it builds and deploys automatically on every
push, gives you a permanent `https://` URL with no certificate setup, and
lets you attach a small persistent disk so the SQLite tracking database
survives restarts and deploys.

1. Push this repo to GitHub if it isn't already.
2. On Render: **New → Web Service** → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Instance type: pick a paid **Starter** tier or above — the free tier
   spins down when idle, which breaks both the webhook (it needs to be
   awake to receive messages any time) and the follow-up scheduler (it
   needs to keep running in the background to check for overdue requests).
6. Add a **Persistent Disk**, mounted at `/opt/render/project/src/data`
   (or wherever you clone to + `/data`) — this is where `data/tracking.db`
   lives. Without this, every deploy wipes your tracking history.
7. Once deployed, Render shows you the service's public URL, e.g.
   `https://whatsapp-correction-bot.onrender.com`. That's your
   `<your-host>` for the rest of this guide.

(Railway and Fly.io are reasonable alternatives with a similar deploy-from-git
model and persistent volumes, if you'd rather use one of those.)

#### Option B: free hosting on Oracle Cloud

If avoiding a recurring hosting bill matters more than convenience, Oracle
Cloud's **"Always Free"** tier includes a small VM that runs 24/7 at $0
indefinitely (not a trial). It's more setup work than Render — you're
managing a real server instead of clicking through a dashboard — but
`deploy/setup-server.sh` in this repo automates nearly all of it.

1. Create an account at [cloud.oracle.com](https://cloud.oracle.com). Oracle
   requires a card on file for identity verification even for the free
   tier, but the Always Free resources are not billed.
2. Create a VM instance: **Compute → Instances → Create Instance**. Pick an
   **Always Free–eligible shape** (e.g. `VM.Standard.A1.Flex` or
   `VM.Standard.E2.1.Micro`), Ubuntu as the image, and download the SSH key
   pair Oracle generates during creation — you'll need the private key file
   to connect.
3. In the VM's networking settings (or the subnet's **Security List** /
   **Network Security Group**), add ingress rules allowing TCP ports
   **22** (SSH), **80**, and **443** from `0.0.0.0/0`. This is a
   cloud-level firewall separate from the OS — the setup script can't do
   this step for you.
4. SSH in and clone the repo:
   ```bash
   ssh -i /path/to/downloaded-key.pem ubuntu@<instance-public-ip>
   git clone https://github.com/evaamin/whatsapp-correction-bot.git
   cd whatsapp-correction-bot
   cp .env.example .env      # then fill in real credentials
   cp centers.example.json centers.json   # then fill in real center numbers
   ```
5. Run the setup script:
   ```bash
   bash deploy/setup-server.sh
   ```
   It installs Python and [Caddy](https://caddyserver.com) (a reverse proxy
   that provisions free HTTPS certificates automatically), sets up a
   virtualenv, registers the bot as a systemd service that restarts on
   crash or reboot, and prints the public HTTPS URL to use as `<your-host>`
   for the rest of this guide — no domain purchase needed, it uses a free
   [nip.io](https://nip.io) hostname that maps to the VM's IP.
6. After editing `.env` or `centers.json` later, restart the service:
   ```bash
   sudo systemctl restart whatsapp-bot
   ```
   Check logs with `sudo journalctl -u whatsapp-bot -f`.

### 3. Fill in environment variables

If you're on Render, set these under the service's **Environment** tab
(not in a committed `.env` file — Render's dashboard is where secrets
actually live in production). If you're on Oracle Cloud, edit `.env`
directly on the server as shown in step 2 above. Locally, put the same
values in your own `.env` file.

| Variable | Value |
|---|---|
| `WHATSAPP_PROVIDER` | `meta` |
| `WHATSAPP_ACCESS_TOKEN` | From Meta App Dashboard → WhatsApp → API Setup |
| `WHATSAPP_PHONE_NUMBER_ID` | Same page — the "Phone number ID", not the phone number itself |
| `WHATSAPP_VERIFY_TOKEN` | Any string you make up (e.g. a random password) — you'll reuse it in step 4 |
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com) — needs billing credit added; classification is cheap (a fraction of a cent per reply) but requires a non-zero balance |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` (already the default — fast and cheap, fine for this task) |
| `COORDINATOR_WHATSAPP_NUMBER` | The coordinator's WhatsApp number, format `whatsapp:+15551234567` |

Note on the access token: the one generated in API Setup is temporary
(~24h). For anything longer-running, generate a permanent token via a
System User in Meta Business Settings instead, so the bot doesn't stop
working after a day.

### 4. Point Meta's webhook at your deployment

In the Meta App Dashboard → WhatsApp → Configuration:

1. Callback URL: `https://<your-host>/webhook/whatsapp/meta`
2. Verify token: the same string you set as `WHATSAPP_VERIFY_TOKEN`
3. Click **Verify and Save** — Meta calls the URL once to confirm you
   control it; this should succeed instantly if the app is deployed and
   running.
4. Subscribe to the **`messages`** webhook field.
5. **Also required, easy to miss:** the WhatsApp Business Account itself
   has to be subscribed to *this app* to actually deliver events — ticking
   the checkbox in step 4 alone doesn't guarantee that. If messages you
   send never trigger anything on your server, confirm the subscription
   with:
   ```bash
   curl -X POST "https://graph.facebook.com/v21.0/<WABA_ID>/subscribed_apps" \
     -H "Authorization: Bearer <WHATSAPP_ACCESS_TOKEN>"
   ```
   (`WABA_ID` is the WhatsApp Business Account ID shown on the API Setup
   page.)

### 5. Add the real center numbers

Edit `centers.json` (this file is gitignored — it stays local/private to
each deployment, never committed):

```json
{
  "clinicA": "whatsapp:+15551230001",
  "clinicB": "whatsapp:+15551230002"
}
```

### 6. Check the recipient limits before rolling out to everyone

- **Test-number recipient cap.** If you're still on Meta's free test
  number (from API Setup, not a verified business number), it can only
  message up to 5 phone numbers you've manually added as test recipients.
  To message a real center list you need a verified WhatsApp Business
  Profile — set that up in the Meta dashboard before rollout if you
  haven't already; it takes real review time, so start it early.
- **The 24-hour session window.** WhatsApp only allows free-form,
  business-initiated messages (like the "New correction request" push) to
  someone who has messaged your number within the last 24 hours —
  otherwise the send fails. Easiest fix: have each center send any message
  ("hi") to the business number once, before you start routing requests to
  them. For a fully hands-off production flow, you'd instead set up an
  approved message template with Meta for the initial outreach.
- **A failed delivery to one center never breaks another's.**
  `app/messaging.py` logs failures instead of crashing the request — if a
  reply seems to have gone missing, check the server logs for
  `Failed to send WhatsApp message`.

### 7. Test it for real

From your own phone (added as a test recipient, or once verified as a
production number):

```bash
python cli_dry_run.py send clinicA "Please fix the intake form field"
```

This creates the tracking record locally and sends the real WhatsApp
message through your deployed service's configured provider. Reply from
WhatsApp and confirm the webhook picks it up — check
`https://<your-host>/requests` to see the record update.

Inspection routes on the running service: `GET /health` (provider +
Anthropic configuration status), `GET /requests` (JSON dump of all tracked
requests).

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
