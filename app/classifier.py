"""Classifies a center's WhatsApp reply as a plain acknowledgement vs. a
substantive response, using the Claude API.

Falls back to a simple keyword heuristic when no ANTHROPIC_API_KEY is
configured, so the request/response/follow-up flow can be exercised end to
end in dry-run mode without live credentials (see cli_dry_run.py).
"""

from __future__ import annotations

from app.config import settings

ACKNOWLEDGEMENT = "acknowledgement"
SUBSTANTIVE = "substantive"

_CLASSIFICATION_PROMPT = """A coordinator sent this correction request to a center over WhatsApp:

---
{request_text}
---

The center replied:

---
{reply_text}
---

Classify the center's reply as exactly one of:
- "acknowledgement" — a plain acknowledgement with no real content (e.g. "ok", \
"received", "on it", "thanks, will check", a thumbs up). It confirms receipt \
but doesn't say anything about the correction itself.
- "substantive" — a response that actually addresses the correction: it \
explains what was done, asks a clarifying question, pushes back, reports the \
issue is fixed, or otherwise adds real content beyond confirming receipt.

Respond with exactly one word: either "acknowledgement" or "substantive". \
No other text."""


_ACK_PHRASES = {
    "ok",
    "okay",
    "k",
    "kk",
    "noted",
    "done",
    "received",
    "got it",
    "on it",
    "will check",
    "checking",
    "thanks",
    "thank you",
    "ack",
    "yes",
    "sure",
    "👍",
}

# Individual words that, on their own, only ever signal a plain
# acknowledgement — used to classify short multi-word replies like
# "ok, will check" without misreading real content as an ack.
_ACK_WORDS = {
    "ok",
    "okay",
    "k",
    "kk",
    "noted",
    "done",
    "received",
    "got",
    "it",
    "on",
    "will",
    "check",
    "checking",
    "thanks",
    "thank",
    "you",
    "ack",
    "yes",
    "sure",
    "and",
    "👍",
}


def _heuristic_classify(reply_text: str) -> str:
    """Keyword-based fallback used when no Claude API key is configured."""
    text = reply_text.strip().lower()
    # Strip trailing sentence punctuation (but not emoji) for a clean match.
    stripped = text.rstrip(".! ")
    if stripped in _ACK_PHRASES:
        return ACKNOWLEDGEMENT

    # Short replies made up entirely of ack-ish words (e.g. "ok, will check").
    words = [w.strip(".,!") for w in stripped.split()]
    words = [w for w in words if w]
    if words and len(stripped) <= 30 and all(w in _ACK_WORDS for w in words):
        return ACKNOWLEDGEMENT

    return SUBSTANTIVE


def classify_reply(request_text: str, reply_text: str) -> str:
    """Returns ACKNOWLEDGEMENT or SUBSTANTIVE."""
    if not settings.anthropic_configured:
        return _heuristic_classify(reply_text)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16,
        messages=[
            {
                "role": "user",
                "content": _CLASSIFICATION_PROMPT.format(
                    request_text=request_text, reply_text=reply_text
                ),
            }
        ],
    )

    if response.stop_reason == "refusal":
        # Safety classifiers declined for some reason — fall back to the
        # heuristic rather than blocking the flow.
        return _heuristic_classify(reply_text)

    text_blocks = [block.text for block in response.content if block.type == "text"]
    answer = "".join(text_blocks).strip().lower()

    if ACKNOWLEDGEMENT in answer:
        return ACKNOWLEDGEMENT
    if SUBSTANTIVE in answer:
        return SUBSTANTIVE
    # Unexpected output — default to substantive so nothing gets silently
    # marked as a rubber-stamp acknowledgement.
    return SUBSTANTIVE
