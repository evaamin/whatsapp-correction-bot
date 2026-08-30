# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A WhatsApp bot that replaces a manual Excel-based correction-tracking
workflow: a coordinator sends a correction request naming a center, the
bot forwards it, classifies the center's reply (acknowledgement vs.
substantive) via the Claude API, and auto-nudges centers that go quiet.
Full behavioral description is in `README.md` → "How it works".

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest tests/ -v                                  # full suite
pytest tests/test_classifier.py -v                 # one file
pytest tests/test_classifier.py::test_name -v       # one test

uvicorn app.main:app --reload                       # run the server locally

python cli_dry_run.py centers                        # exercise the app without any credentials
```

`cli_dry_run.py` and the test suite both work with zero credentials
configured — no `ANTHROPIC_API_KEY` means replies are classified with a
keyword heuristic instead of the Claude API, and no WhatsApp provider
credentials means outbound messages are printed instead of sent. See
`README.md` → "Local dry-run / testing" for the full command set.

## Architecture

**`app/state_machine.py` is the single source of truth for all tracking
logic**, and the three entry points below all call into it identically
rather than duplicating logic:

- `app/main.py` (the FastAPI webhook, both Twilio and Meta variants)
- `app/scheduler.py` (the background follow-up job)
- `cli_dry_run.py` (local testing without any live service)

This means a bug reproduced via the CLI is the same bug the live webhook
would hit — there's no separate "test path" logic to keep in sync.

**Dual WhatsApp provider support** (`app/messaging.py`): `WHATSAPP_PROVIDER`
selects Twilio or Meta's Cloud API directly. Phone numbers are handled
uniformly as `whatsapp:+1...` everywhere else in the app (`centers.json`,
`COORDINATOR_WHATSAPP_NUMBER`, the DB); `messaging.py` is the only place
that translates that into whatever shape each provider's API wants.
`send_message()` catches and logs delivery failures rather than raising —
one center's failed delivery shouldn't crash the request for every other
center.

**Two webhook shapes, one handler** (`app/main.py`): Twilio posts
form-encoded fields to a single route; Meta requires a `GET` verification
handshake plus a `POST` with deeply nested JSON (`entry[].changes[].value`).
Both funnel into a shared `_handle_inbound_message()` before reaching
`state_machine`.

**Classification fallback** (`app/classifier.py`): calls the Claude API
when `ANTHROPIC_API_KEY` is set, otherwise falls back to a keyword
heuristic. Note: `claude-haiku-4-5` (the configured default) does not
support the `output_config.effort` parameter — don't add it back without
checking model support first, it was removed after causing a 400.

**Config loading** (`app/config.py`): the only module that reads
`.env`/`centers.json`; everything else imports `settings` from here rather
than touching environment variables directly.

**Storage** (`app/db.py`): the only module with raw SQL. SQLite file at
`DB_PATH` (default `data/tracking.db`), gitignored.

## Helping a user deploy this

`README.md` → "Setup walkthrough (deploying this for real)" is a complete,
ordered, non-technical walkthrough (local run → host deployment → env vars
→ Meta webhook registration → real center numbers → pre-rollout gotchas →
end-to-end test). If someone opens this repo and asks for help setting it
up, work through that section with them interactively — run the commands,
help them fill in `.env`/`centers.json`, and troubleshoot each step —
rather than just pointing them at the file.

Two hosting paths are documented (Render, or a free Oracle Cloud VM via
`deploy/setup-server.sh` + `deploy/whatsapp-bot.service`); either requires
account creation only the user can do (identity/payment verification), but
once they have SSH access to a VM, the rest can be driven from here.

A few non-obvious gotchas discovered while setting this up for real, worth
knowing before troubleshooting a deployment:

- **Meta requires an explicit subscription step** beyond registering the
  webhook URL and ticking "messages" in the dashboard — the WhatsApp
  Business Account itself must be subscribed to *this app*:
  `POST /v21.0/{waba_id}/subscribed_apps` with the access token. Skipping
  this is the most likely cause of "webhook verifies fine, but nothing
  ever arrives when a message is sent."
- **Meta's API Setup access token is temporary (~24h).** For anything
  longer-running, generate a permanent token via a Meta Business System
  User instead.
- **The 24-hour session window**: WhatsApp rejects free-form
  business-initiated messages (error code 131047) to anyone who hasn't
  messaged the business number in the last 24 hours. Have the recipient
  send any message first to open the window before testing sends to them.
- **Meta test numbers cap out at 5 manually-added recipients** — going
  beyond that requires WhatsApp Business Profile verification through
  Meta, which takes real review time.

## Support channel

Bug reports and feature requests go through this repo's GitHub Issues, per
`README.md`.
