"""Noise filtering and theme classification for AccessRP support tickets.

Themes are detected via keyword rules tuned to what actually appears in the
Q1 2026 export. A ticket can match multiple themes; `themes_list` holds all
matches and `theme_primary` is the first match (priority order below).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

import pandas as pd

NOISE_SERVICE = "Ads Test Tickets and Auto-Emails"

# Subjects that are obviously automation, regardless of service.
NOISE_SUBJECT_PATTERNS = [
    r"^your message couldn'?t be delivered",
    r"submission confirmation",
    r"appointment booked automation trigger",
    r"appointment reschedule automation trigger",
    r"please book appointment",
    r"end user digest",
    r"adgmtenant-alert",
    r"^test$",
    r"^\s*$",
]
_NOISE_RE = re.compile("|".join(NOISE_SUBJECT_PATTERNS), re.IGNORECASE)

# Theme rules: (theme_name, list of regex patterns). Order matters — first
# match wins for `theme_primary`. Patterns run against subject + description.
THEME_RULES: list[tuple[str, list[str]]] = [
    ("Login / Access",
     [r"\b(?:login|log\s?in|sign\s?in|access denied|cannot access|can'?t access|"
      r"otp|password|account locked|2fa)\b"]),
    ("Payment / Wallet",
     [r"\b(?:payment|wallet|top[- ]?up|refund|charge|charged|transaction failed|"
      r"deduct|invoice|fees?)\b"]),
    ("Application stuck / pending",
     [r"\b(?:stuck|pending|not moving|no update|status not|awaiting|waiting for|"
      r"under review)\b"]),
    ("Application not found / missing",
     [r"\b(?:not found|missing|cannot find|can'?t find|disappeared|where is)\b"]),
    ("Rejection / declined",
     [r"\b(?:rejected|declined|denied|refused|disapproved)\b"]),
    ("Cancellation request",
     [r"\b(?:cancel|cancellation|withdraw|withdrawal)\b"]),
    ("Data correction / update",
     [r"\b(?:update|correction|wrong|incorrect|mistake|typo|change my|"
      r"need to change|amend)\b"]),
    ("Document / attachment issue",
     [r"\b(?:document|attachment|upload|file size|file format|pdf|signed|"
      r"signature|noc)\b"]),
    ("Certificate",
     [r"\b(?:certificate|certif|noc letter|good standing)\b"]),
    ("Lease / tenancy",
     [r"\b(?:lease|tenancy|tenant|landlord|rental|ejari)\b"]),
    ("Transfer / POA",
     [r"\b(?:transfer|poa|power of attorney|assignment)\b"]),
    ("Appointment / booking",
     [r"\b(?:appointment|booking|reschedule|book a slot)\b"]),
    ("Error / system issue",
     [r"\b(?:error|failed|failure|broken|bug|crash|cannot submit|"
      r"can'?t submit|something went wrong)\b"]),
    ("Slow / performance",
     [r"\b(?:slow|takes too long|loading|spinning|timeout|timed out)\b"]),
    ("Arabic-language ticket",
     [r"[؀-ۿ]"]),
]

_THEME_COMPILED = [
    (name, re.compile("|".join(pats), re.IGNORECASE))
    for name, pats in THEME_RULES
]

# Words to drop when computing n-grams.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "being", "with", "from", "as",
    "i", "you", "we", "he", "she", "it", "they", "this", "that", "these",
    "those", "my", "your", "our", "their", "his", "her", "its", "fw", "re",
    "please", "kindly", "dear", "sir", "madam", "team", "regards", "thanks",
    "thank", "hi", "hello", "support", "ticket", "case", "number", "no",
    "not", "have", "has", "had", "do", "does", "did", "can", "could", "would",
    "should", "may", "might", "will", "shall", "am", "pm", "automation",
    "trigger", "automatic", "message", "email", "mail", "notification",
    "adgm", "accessrp", "application", "real", "estate", "property", "id",
    "ref", "reference", "external", "internal",
}


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Add `is_noise`, `themes_list`, and `theme_primary` columns to df."""
    out = df.copy()
    subj = out["subject"].astype("string").fillna("")
    desc = out["description_text"].astype("string").fillna("")

    service_is_noise = out["custom_fields.cf_service"].astype("string") == NOISE_SERVICE
    subject_is_noise = subj.str.contains(_NOISE_RE, na=False)
    out["is_noise"] = service_is_noise | subject_is_noise

    combined = (subj + " " + desc).str.lower()
    matches: list[list[str]] = [[] for _ in range(len(out))]
    for name, regex in _THEME_COMPILED:
        hit = combined.str.contains(regex, na=False).to_numpy()
        for i, h in enumerate(hit):
            if h:
                matches[i].append(name)

    out["themes_list"] = matches
    out["theme_primary"] = [m[0] if m else "Other / unclassified" for m in matches]
    out.loc[out["is_noise"], "theme_primary"] = "Noise (automation)"
    return out


_WORD_RE = re.compile(r"[a-z][a-z'-]{2,}", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    toks = _WORD_RE.findall(text.lower())
    return [t for t in toks if t not in _STOPWORDS and not t.isdigit()]


def top_ngrams(texts: Iterable[str], n: int = 2, k: int = 30) -> pd.DataFrame:
    """Return a DataFrame of the top-k most frequent n-grams across `texts`."""
    counter: Counter[str] = Counter()
    for t in texts:
        if not isinstance(t, str):
            continue
        toks = _tokens(t)
        if len(toks) < n:
            continue
        for i in range(len(toks) - n + 1):
            counter[" ".join(toks[i : i + n])] += 1
    rows = counter.most_common(k)
    return pd.DataFrame(rows, columns=[f"{n}-gram", "count"])


def theme_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-theme counts, top service, and average sentiment.

    Uses `themes_list` (multi-label) — a ticket counts toward every theme it
    matches, so the total can exceed len(df).
    """
    if "themes_list" not in df.columns:
        df = classify(df)
    exploded = (
        df[~df["is_noise"]]
        .explode("themes_list")
        .rename(columns={"themes_list": "theme"})
    )
    exploded = exploded[exploded["theme"].notna()]
    grouped = (
        exploded.groupby("theme")
        .agg(
            tickets=("id", "size"),
            avg_sentiment=("sentiment_score", "mean"),
            top_service=(
                "custom_fields.cf_service",
                lambda s: s.value_counts().idxmax() if s.notna().any() else None,
            ),
        )
        .reset_index()
        .sort_values("tickets", ascending=False)
    )
    grouped["avg_sentiment"] = grouped["avg_sentiment"].round(1)
    return grouped
