from __future__ import annotations

import re
from dataclasses import dataclass

@dataclass
class SecurityResult:
    safe: bool
    reason: str = ""

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", re.I), "private key"),
    (re.compile(r"\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd)\b\s*[:=]\s*\S+", re.I), "credential assignment"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "API-style secret"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"\b(?:seed phrase|mnemonic)\b\s*[:=]\s*(?:[a-z]+\s+){7,}[a-z]+", re.I), "seed phrase"),
]

HIGH_RISK_LABELS = re.compile(
    r"\b(?:aadhaar|aadhar|pan number|passport number|bank account|routing number|cvv|pin code for account)\b",
    re.I,
)

# Candidate payment-card-shaped runs: 13-19 digits, optionally split by spaces or
# hyphens only every 4 digits (real card formatting), never at arbitrary offsets.
# This alone still matches plenty of non-card numbers (IDs, ranges), so a Luhn
# check below decides — real card numbers pass it, and an arbitrary digit run
# has only ~1-in-10 odds of doing so (issue #4).
_CARD_CANDIDATE_RE = re.compile(r"\b\d{4}(?:[ -]?\d{4}){2,3}(?:[ -]?\d{1,3})?\b")

def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

def _looks_like_card(text: str) -> bool:
    for m in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return True
    return False

def check_text(text: str) -> SecurityResult:
    t = text.strip()
    if not t:
        return SecurityResult(False, "empty memory")
    if len(t) > 1500:
        return SecurityResult(False, "memory is too long; store a durable compressed fact instead")
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(t):
            return SecurityResult(False, f"probable sensitive data detected: {label}")
    if _looks_like_card(t):
        return SecurityResult(False, "probable sensitive data detected: possible payment/account number")
    if HIGH_RISK_LABELS.search(t):
        return SecurityResult(False, "probable sensitive identifier")
    return SecurityResult(True, "")
