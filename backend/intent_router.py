# backend/intent_router.py
"""
Lightweight, deterministic intent router for the NTPC chatbot.

Classifies an incoming chat message via regex/keyword matching ONLY — no LLM,
no network, no new dependencies (just `re` + `random`). Small-talk and
meta-questions get a canned reply and bypass RAG entirely; everything else is
routed to the existing RAG pipeline.

Public API:
    classify_intent(user_message: str) -> str   # returns an intent label
    get_response(intent: str) -> str            # random canned reply for that intent

Intent labels:
    GREETING, THANKS, GOODBYE, HOW_ARE_YOU, IDENTITY_HELP,
    UNCLEAR, DOCUMENT_QUESTION
"""

import random
import re

# ── Intent labels ────────────────────────────────────────────
GREETING = "GREETING"
THANKS = "THANKS"
GOODBYE = "GOODBYE"
HOW_ARE_YOU = "HOW_ARE_YOU"
IDENTITY_HELP = "IDENTITY_HELP"
UNCLEAR = "UNCLEAR"
DOCUMENT_QUESTION = "DOCUMENT_QUESTION"

# Greeting/thanks/goodbye/small-talk only apply to SHORT messages; anything
# longer is treated as a real question (prevents "hi, what was profit in 2023"
# from being mistaken for a greeting).
MAX_SHORTTALK_WORDS = 6

# Punctuation stripped from the message ends before matching.
_EDGE = " \t\n\r\f\v.,!?;:\"'`~-_/\\()[]{}…"

# ── Patterns (checked in this order; first hit wins) ─────────
# Compiled case-insensitive. Matched against the lower-cased, edge-stripped core.
_PATTERNS: list[tuple[str, list[str]]] = [
    (IDENTITY_HELP, [
        r"\bwho (are|r) (you|u)\b",
        r"\bwhat (are|r) (you|u)\b",
        r"\bwhat'?s your name\b",
        r"\bare (you|u) (a |an )?(human|bot|ai|robot|machine|real person|person)\b",
        r"\bwhat can (you|u) do\b",
        r"\bwhat do (you|u) do\b",
        r"\b(can|could) (you|u) help\b",
        r"\bhow can (you|u) help\b",
        r"^help$",                      # standalone "help" only
    ]),
    (HOW_ARE_YOU, [
        r"\bhow (are|r) (you|u|ya)\b",
        r"\bhow'?s it going\b",
        r"\bhow are things\b",
        r"\bhow do you do\b",
        r"\bhru\b",
        r"\bwhat'?s up\b",
        r"\bwassup\b",
        r"\bsup\b",
    ]),
    (GOODBYE, [
        r"\bbye+\b",
        r"\bgoodbye\b",
        r"\bsee (you|ya|u)\b",
        r"\bcya\b",
        r"\btake care\b",
        r"\b(talk|chat|catch you) later\b",
    ]),
    (THANKS, [
        r"\bthanks?\b",                 # thank, thanks
        r"\bthank (you|u)\b",
        r"\bthanks a lot\b",
        r"\b(thx|thnx|tysm|ty)\b",
        r"\bmuch appreciated\b",
        r"\b(appreciate it|appreciated)\b",
        r"\bgot it\b",
        r"^(ok(ay)?|kk?|k)$",           # bare "ok"/"okay"/"k" → treat as THANKS
    ]),
    (GREETING, [
        r"\bhi+\b",                     # hi, hii, hiiii
        r"\bhey+\b",                    # hey, heyy
        r"\bhello+\b",                  # hello, hellooo
        r"\bhelo\b",                    # common typo
        r"\bhiya\b",
        r"\b(namaste|namaskar)\b",
        r"\bgood (morning|afternoon|evening|day)\b",
        r"\bgreetings\b",
    ]),
]
_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (intent, [re.compile(p, re.IGNORECASE) for p in pats]) for intent, pats in _PATTERNS
]

# ── Canned responses (one picked at random per request) ──────
_RESPONSES: dict[str, list[str]] = {
    GREETING: [
        "Hi there! 👋 I'm the NTPC knowledge assistant. How can I help you today?",
        "Hello! Ask me anything about NTPC annual reports, OS/TC documents, EDOP, or employee info.",
        "Hey! What would you like to know?",
        "Namaste! 🙏 How can I help you today?",
        "Hi! I'm here to help with NTPC documents and information. What's your question?",
    ],
    THANKS: [
        "You're welcome! Let me know if you need anything else.",
        "Happy to help!",
        "Anytime! 😊",
        "Glad I could help. Anything else?",
    ],
    GOODBYE: [
        "Goodbye! Have a great day.",
        "Take care! 👋",
        "See you later!",
        "Bye! Reach out anytime you need NTPC info.",
    ],
    HOW_ARE_YOU: [
        "I'm doing great, thanks for asking! How can I help you today?",
        "All good here! What would you like to know?",
    ],
    IDENTITY_HELP: [
        "I'm the NTPC internal knowledge assistant. I can answer questions about NTPC annual "
        "reports, OS/TC documents, EDOP policies, and employee experience information. "
        "What would you like to know?",
        "I'm a chatbot built to help NTPC staff find information from internal documents and "
        "reports. Try asking me a question!",
    ],
    UNCLEAR: [
        "Could you rephrase that? You can ask me about NTPC annual reports, internal documents, "
        "EDOP, or employee info.",
    ],
}


def classify_intent(user_message: str) -> str:
    """Return an intent label for `user_message` using regex/keyword rules only."""
    raw = (user_message or "").strip()
    core = raw.strip(_EDGE).lower().strip()

    # Empty or punctuation-only → unclear.
    if not core:
        return UNCLEAR

    words = core.split()
    word_count = len(words)

    # Long messages are real questions — never small-talk.
    if word_count > MAX_SHORTTALK_WORDS:
        return DOCUMENT_QUESTION

    # Short message: try the small-talk / meta patterns in priority order.
    for intent, patterns in _COMPILED:
        if any(p.search(core) for p in patterns):
            return intent

    # Unmatched: a lone, very short token is unclear; otherwise a real question.
    if word_count == 1 and len(core) < 3:
        return UNCLEAR
    return DOCUMENT_QUESTION


def get_response(intent: str) -> str:
    """Return a random canned reply for a non-document intent."""
    return random.choice(_RESPONSES.get(intent, _RESPONSES[UNCLEAR]))
