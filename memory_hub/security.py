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
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "possible payment/account number"),
]

HIGH_RISK_LABELS = re.compile(
    r"\b(?:aadhaar|aadhar|pan number|passport number|bank account|routing number|cvv|pin code for account)\b",
    re.I,
)

def check_text(text: str) -> SecurityResult:
    t = text.strip()
    if not t:
        return SecurityResult(False, "empty memory")
    if len(t) > 1500:
        return SecurityResult(False, "memory is too long; store a durable compressed fact instead")
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(t):
            return SecurityResult(False, f"probable sensitive data detected: {label}")
    if HIGH_RISK_LABELS.search(t):
        return SecurityResult(False, "probable sensitive identifier")
    return SecurityResult(True, "")
