from app import classifier


def test_heuristic_classifies_short_acks():
    for text in ["ok", "Ok!", "noted", "done", "thanks", "👍", "got it"]:
        assert classifier.classify_reply("fix the form", text) == classifier.ACKNOWLEDGEMENT


def test_heuristic_classifies_substantive_replies():
    replies = [
        "Fixed — the intake form field now requires a valid date.",
        "Can you clarify which field on the form you mean?",
        "We checked and the issue is actually with the printer, not the form.",
    ]
    for text in replies:
        assert classifier.classify_reply("fix the form", text) == classifier.SUBSTANTIVE
