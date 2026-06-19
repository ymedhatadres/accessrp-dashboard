"""Generate the static UX-research HTML report for AccessRP.

Structure mirrors the Dari reference (Rahaf Sh.) — 5-card hero KPI strip,
9 tabs, Chart.js charts, narrative pain-category cards, ticket browser.
AccessRP content underneath, PII redacted in embedded quotes.

Usage:
    python3 build_report.py                       # latest month (auto)
    python3 build_report.py --month 2026-05       # specific month
    python3 build_report.py --quarter "2026 Q1"   # full quarter
    python3 build_report.py --all
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from lib.text_clean import clean_description, extract_sentences  # noqa: E402
from lib.themes import classify  # noqa: E402

PARQUET = Path(__file__).parent / "data" / "tickets.parquet"
OUT_HTML = Path(__file__).parent / "docs" / "index.html"


# ----------------------------------------------------------------------------
# PII redaction
# ----------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}")
_EID_RE = re.compile(r"\b\d{3}[-\s]?\d{4}[-\s]?\d{7}[-\s]?\d\b")
_LONGREF_RE = re.compile(r"\b\d{12,}\b")
_UNIT_RE = re.compile(r"\bUNT\d+\b", re.IGNORECASE)
_LICENSE_RE = re.compile(r"\bCN-\d+\b", re.IGNORECASE)
_PASSPORT_RE = re.compile(r"\b[A-Z]\d{7,9}\b")
_URL_RE = re.compile(r"https?://\S+")


def redact(text: str) -> str:
    if not text:
        return ""
    t = text
    t = _URL_RE.sub("[url]", t)
    t = _EMAIL_RE.sub("[email]", t)
    t = _EID_RE.sub("[id]", t)
    t = _LONGREF_RE.sub("[ref]", t)
    t = _UNIT_RE.sub("[unit]", t)
    t = _LICENSE_RE.sub("[license]", t)
    t = _PASSPORT_RE.sub("[passport]", t)
    t = _PHONE_RE.sub("[phone]", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ----------------------------------------------------------------------------
# Theme -> pain category mapping (the 5 mirror categories from Dari report)
# ----------------------------------------------------------------------------

THEME_TO_CATEGORY = {
    "Login / Access":                   "self_service",
    "Cancellation request":             "self_service",
    "Data correction / update":         "self_service",
    "Transfer / POA":                   "self_service",
    "Document / attachment issue":      "self_service",

    "Payment / Wallet":                 "unclear_errors",
    "Application stuck / pending":      "unclear_errors",
    "Application not found / missing":  "unclear_errors",
    "Error / system issue":             "unclear_errors",
    "Slow / performance":               "unclear_errors",

    "Rejection / declined":             "hidden_rules",
    "Certificate":                      "hidden_rules",
    "Lease / tenancy":                  "hidden_rules",

    "Information request":              "data_sync",

    "Appointment / booking":            "helpdesk_noise",
}

# Narrative content for each of the 5 mirror pain categories — AccessRP-specific.
PAIN_CATEGORIES = {
    "self_service": {
        "title": "Self-Service Gaps",
        "subtitle": "Users email support for routine actions they should be able to do themselves.",
        "why": "AccessRP is built around formal application submissions. Routine "
               "data-maintenance actions — updating an email or phone, refreshing a "
               "trade-license, amending or cancelling a draft, transferring "
               "ownership, uploading or replacing a document — have no in-product "
               "path. Users send a support request every time.",
        "fix": "Build an in-product profile editor for personal and company "
               "information; add self-serve cancel / amend for in-flight "
               "applications; expose document re-upload and ownership-transfer "
               "flows directly inside the relevant service.",
        "color": "#2E7D32",
        "bg": "#e8f5e9",
    },
    "unclear_errors": {
        "title": "Unclear System Errors",
        "subtitle": "When something breaks, the user is left without explanation or a way forward.",
        "why": "Failures surface as opaque states — payments deducted with no "
               "receipt, applications stuck in unspecified workflow stages, generic "
               "'something went wrong' screens with no reference code, applications "
               "that simply disappear. Users have no diagnostic information, no "
               "code to quote when contacting support, and no in-product status to "
               "check.",
        "fix": "Replace generic errors with structured messages carrying a reference "
               "code; add an 'application status' page exposing exactly where a "
               "submission sits in the workflow with an ETA; build self-serve "
               "payment-status verification so users can confirm whether the system "
               "saw their payment without raising a ticket.",
        "color": "#C62828",
        "bg": "#ffebee",
    },
    "hidden_rules": {
        "title": "Hidden Service Requirements",
        "subtitle": "Users hit blocking eligibility and business rules they did not know about.",
        "why": "ADGM real-estate enforces many legitimate rules — 90-day automatic "
               "contract closure after expiry, lease-renewal limits on rent "
               "increase, transfer-of-interest prerequisites, certificate / NOC "
               "eligibility. AccessRP enforces these correctly but only surfaces "
               "them after the user has invested time. Rejection wording rarely "
               "explains the specific failing rule.",
        "fix": "Surface eligibility rules on the service card *before* the user "
               "starts a flow. Add pre-flight checks for common blockers (expired "
               "contract, missing licence, eligibility mismatch). When rejecting, "
               "name the specific rule and link to the documentation, and provide "
               "a guided re-submission flow where the issue is fixable.",
        "color": "#F57C00",
        "bg": "#fff3e0",
    },
    "data_sync": {
        "title": "Backend Integration & Data Sync",
        "subtitle": "Records don't propagate between AccessRP and connected ADGM systems.",
        "why": "Licence renewals, ownership changes, unit registrations, and "
               "regulatory information requests are issued or updated in adjacent "
               "systems (licensing, land registry, banks, third-party authorities) "
               "but don't appear in AccessRP — or appear with delays. The "
               "largest pattern in this category is the recurring 'Request for "
               "Information' (طلب معلومات) thread from regulators that lands "
               "in support because no integration handles it directly.",
        "fix": "Audit the connectors between AccessRP and adjacent ADGM systems. "
               "Surface 'last synced' timestamps so users know whether they're "
               "looking at fresh data. Route regulatory-information-request traffic "
               "to a dedicated workflow with the relevant team, not the user-facing "
               "helpdesk.",
        "color": "#1565C0",
        "bg": "#e3f2fd",
    },
    "helpdesk_noise": {
        "title": "Operational Noise & Structured Templates",
        "subtitle": "Form-template emails and routing artefacts inflate ticket volume.",
        "why": "Even after filtering pure automation (delivery failures, "
               "submission confirmations, appointment triggers), a meaningful "
               "share of remaining tickets are structured email templates — "
               "'Please book an appointment for Transfer of Interest' booking "
               "submissions sent through email because no UI exists. These look "
               "like complaints in dashboards but represent missing product "
               "surfaces.",
        "fix": "Replace template-based flows (appointment booking, transfer-of-"
               "interest, structured information requests) with proper in-product "
               "surfaces. Tag template-shaped emails at intake so they're routed "
               "as work items, not lumped into customer-complaint volume.",
        "color": "#6A1B9A",
        "bg": "#f3e5f5",
    },
}

# Keywords used to pull the most salient sentence per theme.
THEME_KEYWORDS = {
    "Login / Access": ["login", "log in", "sign in", "otp", "password", "access"],
    "Payment / Wallet": ["payment", "wallet", "top up", "refund", "deduct", "paid",
                          "دفع", "سداد", "خصم", "مدفوع"],
    "Application stuck / pending": ["stuck", "pending", "waiting", "under review",
                                     "معلق", "قيد"],
    "Application not found / missing": ["not found", "missing", "cannot find",
                                          "غير موجود", "لا يظهر"],
    "Rejection / declined": ["rejected", "declined", "denied", "مرفوض"],
    "Cancellation request": ["cancel", "withdraw", "إلغاء"],
    "Data correction / update": ["update", "wrong", "incorrect", "amend",
                                  "تحديث", "تعديل", "تصحيح"],
    "Document / attachment issue": ["document", "attachment", "upload", "pdf",
                                      "مستند", "وثيقة"],
    "Certificate": ["certificate", "noc", "شهادة"],
    "Lease / tenancy": ["lease", "tenancy", "tenant", "ejari",
                         "إيجار", "ايجار", "مستأجر"],
    "Transfer / POA": ["transfer", "poa", "power of attorney",
                        "تحويل", "وكالة"],
    "Appointment / booking": ["appointment", "booking", "reschedule", "موعد", "حجز"],
    "Error / system issue": ["error", "failed", "broken", "something went wrong",
                              "خطأ", "فشل", "لا يعمل"],
    "Slow / performance": ["slow", "loading", "timeout"],
    "Information request": ["please advise", "request for information",
                             "طلب معلومات", "للاستفسار"],
}


# ----------------------------------------------------------------------------
# Data prep
# ----------------------------------------------------------------------------


def load_full() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET)
    df = classify(df)
    return df.loc[~df["is_noise"]].reset_index(drop=True)


def load_period(month: str | None, quarter: str | None,
                all_data: bool) -> tuple[pd.DataFrame, str]:
    df = load_full()
    if all_data:
        return df, f"{df['created_at'].min():%b %Y} – {df['created_at'].max():%b %Y}"
    if month:
        sub = df[df["created_month"] == month].reset_index(drop=True)
        if sub.empty:
            avail = sorted(df["created_month"].dropna().unique().tolist())
            raise SystemExit(
                f"No tickets in month '{month}'. Available: {avail}")
        label = f"{pd.to_datetime(month).strftime('%B %Y')}"
        return sub, label
    if quarter:
        sub = df[df["quarter"] == quarter].reset_index(drop=True)
        return sub, quarter
    # Default: most recent month that has more than a trivial amount of data.
    counts = df["created_month"].value_counts().sort_index()
    real_months = counts[counts >= 50].index.tolist()
    latest = real_months[-1] if real_months else counts.index[-1]
    sub = df[df["created_month"] == latest].reset_index(drop=True)
    label = pd.to_datetime(latest).strftime("%B %Y")
    return sub, label


def build_all_months(min_size: int = 50) -> tuple[dict, list[tuple[str, str]], str]:
    """Build one DATA block per month + an 'all' block.

    Returns (all_data_dict, options_list, default_month_key).
    options_list is [(key, label), ...] ordered with the most recent month first
    and 'all' last — suitable for the <select> dropdown directly.
    """
    df = load_full()
    counts = df["created_month"].value_counts().sort_index()
    months = [m for m in counts.index if counts[m] >= min_size]

    all_data: dict[str, dict] = {}
    options: list[tuple[str, str]] = []

    for m in reversed(months):  # latest first
        sub = df[df["created_month"] == m].reset_index(drop=True)
        label = pd.to_datetime(m).strftime("%B %Y")
        all_data[m] = build_data(sub, label)
        options.append((m, label))

    # "All" view
    all_label = (f"All months ({df['created_at'].min():%b %Y} – "
                 f"{df['created_at'].max():%b %Y})")
    all_data["all"] = build_data(df, all_label)
    options.append(("all", all_label))

    default_key = options[0][0]  # latest month
    return all_data, options, default_key


def ticket_category(row: pd.Series) -> str | None:
    """Map a ticket to its primary pain category via its first theme match.

    Returns None for un-themed tickets so they don't inflate any of the
    five pain categories.
    """
    for t in (row["themes_list"] or []):
        if t in THEME_TO_CATEGORY:
            return THEME_TO_CATEGORY[t]
    return None


def pick_quote(sub: pd.DataFrame, theme: str | None) -> tuple[str | None, int | None]:
    """Return (cleaned redacted quote, ticket id) for the most negative ticket
    in the slice that has a usable description. None if nothing fits."""
    kw = THEME_KEYWORDS.get(theme or "", []) if theme else []
    cand = (
        sub[sub["description_text"].notna()]
        .sort_values("sentiment_score", ascending=True, na_position="last")
        .head(40)
    )
    for _, r in cand.iterrows():
        c = clean_description(r["description_text"])
        if not c or len(c) < 30:
            continue
        s = extract_sentences(c, kw) if kw else c
        s = redact(s)[:260]
        if len(s) < 25:
            continue
        return s, int(r["id"])
    return None, None


def build_data(df: pd.DataFrame, period_label: str) -> dict:
    df = df.copy()
    df["category"] = df.apply(ticket_category, axis=1)

    total = len(df)
    n_users = int(df["requester.email"].nunique())

    # ---- pain category counts (un-themed tickets excluded) ----
    themed_df = df[df["category"].notna()]
    cat_counts_raw = themed_df["category"].value_counts().to_dict()
    cat_counts = {k: int(cat_counts_raw.get(k, 0)) for k in PAIN_CATEGORIES}
    n_themed = int(themed_df.shape[0])
    n_unthemed = total - n_themed

    top_cat_key = max(cat_counts, key=lambda k: cat_counts[k])
    top_cat_share = cat_counts[top_cat_key] / total * 100 if total else 0
    op_noise_share = cat_counts["helpdesk_noise"] / total * 100 if total else 0

    # ---- top 10 user-facing issues = top 10 themes by ticket count ----
    theme_to_tickets: dict[str, list[int]] = {}
    for _, r in df.iterrows():
        for t in (r["themes_list"] or []):
            theme_to_tickets.setdefault(t, []).append(int(r["id"]))
    theme_counts = sorted(
        ((t, len(ids)) for t, ids in theme_to_tickets.items()),
        key=lambda x: x[1], reverse=True
    )
    top_user_issues = []
    for theme, count in theme_counts[:10]:
        cat_key = THEME_TO_CATEGORY.get(theme, "helpdesk_noise")
        ids = theme_to_tickets[theme]
        sub = df[df["themes_list"].apply(lambda lst, t=theme: t in (lst or []))]
        q_text, q_id = pick_quote(sub, theme)
        sample_ids = sub.sort_values("sentiment_score").head(6)["id"].astype(int).tolist()
        top_user_issues.append({
            "name": theme,
            "description": _issue_description(theme),
            "count": count,
            "pct": round(count / total * 100, 1) if total else 0,
            "category": cat_key,
            "samples": sample_ids[:4],
            "sample_quote": q_text,
            "sample_quote_id": q_id,
        })

    # ---- all issues for distribution table ----
    all_issues = [
        {
            "name": theme,
            "count": count,
            "pct": round(count / total * 100, 1) if total else 0,
            "category": PAIN_CATEGORIES[THEME_TO_CATEGORY.get(theme, "helpdesk_noise")]["title"],
            "category_key": THEME_TO_CATEGORY.get(theme, "helpdesk_noise"),
        }
        for theme, count in theme_counts
    ]

    # ---- top services ----
    svc_counts = df["custom_fields.cf_service"].dropna().value_counts()
    top_services = [(s, int(c)) for s, c in svc_counts.head(5).items()]
    all_services = [(s, int(c)) for s, c in svc_counts.head(10).items()]

    # ---- top issues within each top service ----
    top_service_issues = {}
    for svc, _ in top_services:
        ssub = df[df["custom_fields.cf_service"] == svc]
        local_counts: Counter = Counter()
        for lst in ssub["themes_list"]:
            for t in (lst or []):
                local_counts[t] += 1
        issues = []
        for t, c in local_counts.most_common(4):
            cat_key = THEME_TO_CATEGORY.get(t, "helpdesk_noise")
            q, qid = pick_quote(ssub[ssub["themes_list"].apply(
                lambda lst, x=t: x in (lst or []))], t)
            issues.append({
                "name": t,
                "count": int(c),
                "category": cat_key,
                "sample_quote": q,
                "sample_quote_id": qid,
            })
        top_service_issues[svc] = {
            "total": len(ssub),
            "avg_sentiment": round(float(ssub["sentiment_score"].mean()), 1)
              if ssub["sentiment_score"].notna().any() else None,
            "users": int(ssub["requester.email"].nunique()),
            "top_issues": issues,
            "samples": ssub.sort_values("sentiment_score").head(4)["id"].astype(int).tolist(),
        }

    # ---- service × category table (top 10 services) ----
    cat_keys = list(PAIN_CATEGORIES.keys())
    service_category_table = []
    for svc, total_svc in all_services:
        ssub = df[df["custom_fields.cf_service"] == svc]
        bd = ssub["category"].value_counts().to_dict()
        for k in cat_keys:
            bd.setdefault(k, 0)
        service_category_table.append({
            "service": svc,
            "total": int(total_svc),
            "breakdown": {k: int(bd.get(k, 0)) for k in cat_keys},
        })

    # ---- 5 recurring pain points (one per category, with stats) ----
    pain_points = []
    for k, cfg in PAIN_CATEGORIES.items():
        cat_df = df[df["category"] == k]
        q, qid = pick_quote(cat_df, None)
        sample_ids = cat_df.sort_values("sentiment_score").head(4)["id"].astype(int).tolist()
        pain_points.append({
            "key": k,
            "title": cfg["title"],
            "subtitle": cfg["subtitle"],
            "why": cfg["why"],
            "fix": cfg["fix"],
            "color": cfg["color"],
            "bg": cfg["bg"],
            "count": int(len(cat_df)),
            "pct": round(len(cat_df) / total * 100, 1) if total else 0,
            "sample_quote": q,
            "sample_quote_id": qid,
            "samples": sample_ids,
        })

    # ---- operational issues (helpdesk_noise sub-patterns) ----
    op_df = df[df["category"] == "helpdesk_noise"]
    operational_issues = []
    if not op_df.empty:
        operational_issues.append({
            "name": "Appointment / booking emails",
            "description": "Users emailing support to request, reschedule, or cancel "
                           "appointments because no in-product booking surface exists. "
                           "These look like support tickets but represent a missing UI.",
            "count": int((df["themes_list"].apply(
                lambda lst: "Appointment / booking" in (lst or []))).sum()),
            "samples": op_df.sort_values("sentiment_score").head(4)["id"].astype(int).tolist(),
        })
    transfer_df = df[df["themes_list"].apply(
        lambda lst: "Transfer / POA" in (lst or []))]
    if not transfer_df.empty:
        operational_issues.append({
            "name": "Transfer-of-Interest booking templates",
            "description": "Structured 'Please book appointment for Transfer of Interest' "
                           "emails follow an identical template — they're forms "
                           "submitted through the helpdesk because no product flow "
                           "captures them.",
            "count": int(len(transfer_df)),
            "samples": transfer_df.head(4)["id"].astype(int).tolist(),
        })
    info_df = df[df["themes_list"].apply(
        lambda lst: "Information request" in (lst or []))]
    if not info_df.empty:
        operational_issues.append({
            "name": "Regulatory information-request threads",
            "description": "Recurring 'Request for Information' (طلب معلومات) "
                           "threads from licensing authorities and law-enforcement "
                           "agencies route through the customer-facing helpdesk. "
                           "These distort customer-issue dashboards.",
            "count": int(len(info_df)),
            "samples": info_df.head(4)["id"].astype(int).tolist(),
        })

    # ---- recommendations (8, priority-tagged) ----
    recommendations = [
        ("High", "Build a self-serve profile and company-info editor", "self_service",
         "Removes the largest single source of helpdesk volume.",
         cat_counts.get("self_service", 0)),
        ("High", "Add structured error states with reference codes",
         "unclear_errors",
         "Cuts repeat tickets driven by 'something went wrong' with no diagnostic.",
         cat_counts.get("unclear_errors", 0)),
        ("High", "Expose application status and ETA in-product", "unclear_errors",
         "Most 'application stuck' and 'not found' tickets are visibility "
         "questions answerable by exposing the workflow state.",
         theme_to_tickets.get("Application stuck / pending", []).__len__() +
         theme_to_tickets.get("Application not found / missing", []).__len__()),
        ("High", "Surface eligibility rules on the service card", "hidden_rules",
         "Pre-flight rule visibility prevents users from investing time before "
         "discovering a blocker.",
         cat_counts.get("hidden_rules", 0)),
        ("Medium", "Self-serve payment-status verification", "unclear_errors",
         "Lets users confirm whether the system saw their payment without "
         "raising a ticket.",
         theme_to_tickets.get("Payment / Wallet", []).__len__()),
        ("Medium", "Replace email-based Transfer-of-Interest booking with a form",
         "helpdesk_noise",
         "Removes template-shaped emails from the helpdesk; gives users instant "
         "confirmation.",
         theme_to_tickets.get("Transfer / POA", []).__len__()),
        ("Medium", "Route regulator information-request threads to a dedicated "
         "workflow", "data_sync",
         "Stops regulatory traffic from inflating customer-complaint metrics.",
         theme_to_tickets.get("Information request", []).__len__()),
        ("Low", "Self-serve application cancel / amend for safe types",
         "self_service",
         "Eliminates routine cancel requests that don't need human review.",
         theme_to_tickets.get("Cancellation request", []).__len__()),
    ]
    recommendations = [{
        "priority": p, "title": t, "category_key": k,
        "impact_tickets": int(impact),
        "impact_text": f"~{impact:,} addressable tickets" if impact else "",
        "rationale": r,
    } for (p, t, k, r, impact) in recommendations]

    # ---- trends ----
    arabic_chars = df["description_text"].fillna("").str.contains(r"[؀-ۿ]")
    pct_arabic = arabic_chars.mean() * 100 if total else 0
    sub_eng = df[~arabic_chars]
    sub_ar = df[arabic_chars]
    eng_sent = sub_eng["sentiment_score"].mean()
    ar_sent = sub_ar["sentiment_score"].mean()
    top_service_name, top_service_n = (top_services[0] if top_services else ("—", 0))
    top_service_pct = top_service_n / total * 100 if total else 0
    trends = [
        {"title": f"{pct_arabic:.0f}% of complaints are written in Arabic — they share the same root causes",
         "detail": f"Arabic-language tickets bucket into the same content themes as "
                   f"English-language tickets (Lease, Payment, Data correction, Information "
                   f"request). Average sentiment is similar "
                   f"(EN: {eng_sent:.0f}, AR: {ar_sent:.0f}). Treat them uniformly when "
                   f"prioritising fixes."},
        {"title": f"One service — {top_service_name} — concentrates {top_service_pct:.0f}% of complaints",
         "detail": f"{top_service_n:,} of {total:,} tickets sit in {top_service_name}. "
                   f"Any improvement here delivers the largest immediate volume win."},
        {"title": "Self-service gaps are the single largest pain category",
         "detail": f"{cat_counts.get('self_service', 0):,} tickets "
                   f"({cat_counts.get('self_service', 0)/total*100:.0f}%) come from "
                   f"users asking the helpdesk to perform actions a self-service UI "
                   f"could perform."},
        {"title": "Tagging is sparse — root cause is unknown for ~96% of tickets",
         "detail": "Most tickets close without a tagged root cause / issue source. "
                   "Closing this loop in the helpdesk would let us reason about actual "
                   "system causes, not just user-described symptoms."},
        {"title": "Unclear error states drive the angriest tickets",
         "detail": "Errors, application-stuck, and payment-deducted-no-receipt patterns "
                   "consistently have the lowest sentiment. They're the smallest user "
                   "experience lift per fix."},
        {"title": f"{n_users:,} unique users account for {total:,} complaints",
         "detail": f"Average {total/n_users:.1f} tickets per affected user. A small "
                   f"share of users open many tickets — repeat requesters are concentrated "
                   f"in lease and transfer workflows."},
    ]

    # ---- ticket browser ----
    tickets = []
    for _, r in df.iterrows():
        primary_theme = (r["themes_list"][0] if r["themes_list"] else None)
        cat_key = ticket_category(r)
        tickets.append({
            "id": int(r["id"]),
            "s": str(r.get("custom_fields.cf_service") or "—"),
            "sub": redact(str(r.get("subject") or ""))[:150],
            "q": redact(clean_description(r.get("description_text")))[:240],
            "issue": primary_theme or "Other / unclassified",
            "category": PAIN_CATEGORIES[cat_key]["title"] if cat_key in PAIN_CATEGORIES else "Other",
            "category_key": cat_key,
        })

    # ---- final ----
    return {
        "total": total,
        "n_users": n_users,
        "n_themed": n_themed,
        "n_unthemed": n_unthemed,
        "period": period_label,
        "pain_categories": PAIN_CATEGORIES,
        "cat_counts": cat_counts,
        "top_cat_key": top_cat_key,
        "top_cat_share": round(top_cat_share, 1),
        "op_noise_share": round(op_noise_share, 1),
        "top_user_issues": top_user_issues,
        "all_issues": all_issues,
        "top_services": top_services,
        "all_services": all_services,
        "top_service_issues": top_service_issues,
        "service_category_table": service_category_table,
        "pain_points": pain_points,
        "operational_issues": operational_issues,
        "recommendations": recommendations,
        "trends": trends,
        "tickets": tickets,
    }


def _issue_description(theme: str) -> str:
    """Short one-liner explaining each theme in plain language."""
    return {
        "Lease / tenancy": "Disputes and questions about lease contracts, "
            "tenancies, Ejari/Tawtheeq, and renewal rules.",
        "Data correction / update": "Users email support to update personal or "
            "company details they cannot edit themselves.",
        "Transfer / POA": "Transfer-of-ownership and power-of-attorney requests "
            "that today flow through email rather than a product surface.",
        "Payment / Wallet": "Payment-related issues: money deducted but no receipt, "
            "asked to pay again after a successful charge, wallet/top-up failures.",
        "Information request": "Information-request threads (often in Arabic) from "
            "regulators or users seeking confirmation that lands in support.",
        "Error / system issue": "Generic system errors — 'something went wrong', "
            "failed submissions, broken flows — with no diagnostic.",
        "Certificate": "Certificate and NOC issuance: status visibility, "
            "eligibility, missing/wrong content.",
        "Appointment / booking": "Appointment booking, rescheduling and cancellation "
            "requests sent through email because no in-product booking exists.",
        "Document / attachment issue": "Upload failures, missing or wrong generated "
            "documents (PDFs/NOCs), file-format and size problems.",
        "Application stuck / pending": "Applications sitting in a workflow stage with "
            "no visibility, ETA, or movement.",
        "Cancellation request": "Users asking support to cancel or withdraw an "
            "in-flight application.",
        "Login / Access": "Login, OTP, password and account-access issues.",
        "Application not found / missing": "Applications or records the user "
            "expected to see but cannot find in the product.",
        "Rejection / declined": "Applications rejected or declined, often with "
            "vague reasoning the user has to follow up on.",
        "Slow / performance": "Slow pages, timeouts, loading spinners, perceived "
            "performance issues.",
    }.get(theme, "Recurring pattern across the period.")


# ----------------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------------

CSS = """
:root {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --ink: #1a1a1a;
  --muted: #5d6470;
  --border: #e2e6ec;
  --primary: #0F2D3D;
  --primary-light: #E8EEF2;
  --gold: #B89968;
  --green: #2E7D32; --green-bg: #e8f5e9;
  --red: #C62828; --red-bg: #ffebee;
  --orange: #F57C00; --orange-bg: #fff3e0;
  --blue: #1565C0; --blue-bg: #e3f2fd;
  --purple: #6A1B9A; --purple-bg: #f3e5f5;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
               'Helvetica Neue', Arial, sans-serif;
  background: var(--bg);
  color: var(--ink);
  line-height: 1.6;
  font-size: 14px;
}
.container { max-width: 1320px; margin: 0 auto; padding: 24px; }

/* ---- Hero ---- */
header.hero {
  background: linear-gradient(135deg, #0F2D3D 0%, #1A4A66 100%);
  color: white;
  padding: 56px 24px 64px;
}
header.hero .container { padding: 0 24px; }
header.hero .label {
  font-size: 12px; opacity: 0.7; text-transform: uppercase;
  letter-spacing: 1.2px; margin-bottom: 8px; font-weight: 500;
}
header.hero h1 {
  font-size: 38px; font-weight: 700; margin: 0 0 12px;
  letter-spacing: -0.5px;
  font-family: Georgia, 'Times New Roman', serif;
}
header.hero .subtitle {
  font-size: 18px; opacity: 0.92; font-weight: 400;
  margin-bottom: 24px; max-width: 800px; line-height: 1.5;
}
header.hero .meta { font-size: 13px; opacity: 0.75; }

.kpi-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px; margin-top: 32px;
}
.kpi-card {
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 10px;
  padding: 18px;
  backdrop-filter: blur(10px);
}
.kpi-card .label {
  font-size: 11px; opacity: 0.85; text-transform: uppercase;
  letter-spacing: 0.6px; margin-bottom: 8px; font-weight: 600;
}
.kpi-card .value { font-size: 32px; font-weight: 700; line-height: 1.1; }
.kpi-card .delta { font-size: 12px; opacity: 0.8; margin-top: 6px; }

/* ---- Month picker (in hero) ---- */
.month-picker {
  display: inline-flex; align-items: center; gap: 10px;
  margin-top: 18px;
  background: rgba(255,255,255,0.10);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 8px; padding: 8px 14px;
}
.month-picker label {
  font-size: 12px; opacity: 0.85; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.month-picker select {
  background: white; color: var(--primary);
  border: 1px solid rgba(255,255,255,0.4); border-radius: 6px;
  padding: 6px 28px 6px 12px; font-size: 14px; font-weight: 600;
  cursor: pointer; font-family: inherit;
  appearance: none; -webkit-appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path fill='%230F2D3D' d='M2 4 L6 8 L10 4 Z'/></svg>");
  background-repeat: no-repeat; background-position: right 8px center;
}
.month-picker select:focus { outline: 2px solid var(--gold); outline-offset: 2px; }

/* ---- Tab bar ---- */
nav.tabs {
  background: white; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 50;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
nav.tabs .container {
  display: flex; gap: 4px; overflow-x: auto; padding: 0 24px;
}
nav.tabs button {
  background: none; border: none; padding: 14px 16px;
  font-size: 13px; font-weight: 500; color: var(--muted);
  cursor: pointer; border-bottom: 3px solid transparent;
  white-space: nowrap; transition: color .15s, border-color .15s;
  font-family: inherit;
}
nav.tabs button:hover { color: var(--primary); }
nav.tabs button.active {
  color: var(--primary); border-bottom-color: var(--gold);
  font-weight: 700;
}

/* ---- Sections (tab panels) ---- */
section.tab-content { display: none; padding: 36px 0; }
section.tab-content.active { display: block; }
section h2 {
  font-size: 26px; margin: 0 0 8px; color: var(--primary);
  font-weight: 700;
  font-family: Georgia, 'Times New Roman', serif;
}
section .section-sub {
  color: var(--muted); margin-bottom: 28px;
  font-size: 15px; line-height: 1.6; max-width: 880px;
}

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }

.card {
  background: white; border: 1px solid var(--border); border-radius: 10px;
  padding: 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.card h3 { margin: 0 0 14px; font-size: 17px; font-weight: 700; color: var(--primary); }
.card h4 { margin: 12px 0 4px; font-size: 14px; }
.chart-container { position: relative; height: 380px; }
.chart-container.tall { height: 520px; }

/* ---- Tables ---- */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td {
  text-align: left; padding: 12px 14px;
  border-bottom: 1px solid var(--border); vertical-align: top;
}
th {
  background: var(--primary-light); color: var(--primary);
  font-weight: 700; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.4px;
}
tbody tr:nth-child(even) { background: #fafbfc; }
tbody tr:hover { background: #f0f4f8; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }

/* ---- Pills ---- */
.pill {
  display: inline-block; padding: 3px 10px; border-radius: 20px;
  font-size: 11px; font-weight: 700; line-height: 1.6; white-space: nowrap;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.pill.cat-self_service   { background: var(--green-bg);  color: var(--green); }
.pill.cat-unclear_errors { background: var(--red-bg);    color: var(--red); }
.pill.cat-hidden_rules   { background: var(--orange-bg); color: var(--orange); }
.pill.cat-data_sync      { background: var(--blue-bg);   color: var(--blue); }
.pill.cat-helpdesk_noise { background: var(--purple-bg); color: var(--purple); }
.pill.priority-high      { background: var(--red-bg);    color: var(--red); }
.pill.priority-medium    { background: var(--orange-bg); color: var(--orange); }
.pill.priority-low       { background: var(--green-bg);  color: var(--green); }

/* ---- Quotes & ticket IDs ---- */
.ticket-id {
  font-family: 'SF Mono', Monaco, monospace;
  color: var(--primary); font-weight: 700; font-size: 11px;
}
.quote {
  font-style: italic; padding: 10px 14px;
  border-left: 3px solid var(--gold);
  background: var(--primary-light);
  margin: 8px 0; border-radius: 0 6px 6px 0;
  font-size: 13px; color: #333;
}

/* ---- Issue cards (top issues) ---- */
.issue-card {
  display: grid; grid-template-columns: 56px 1fr; gap: 16px;
  background: white; border: 1px solid var(--border); border-radius: 10px;
  padding: 20px; margin-bottom: 14px;
}
.rank-circle {
  width: 56px; height: 56px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; font-weight: 800;
}
.issue-meta {
  display: flex; gap: 12px; align-items: center;
  font-size: 13px; color: var(--muted); margin-bottom: 8px;
  flex-wrap: wrap;
}
.issue-meta strong { color: var(--ink); }
.issue-name { font-size: 17px; font-weight: 700; margin: 0 0 6px; color: var(--primary); }
.issue-desc { color: var(--ink); font-size: 14px; margin-bottom: 8px; }
.issue-evidence {
  color: var(--muted); font-size: 12px; margin-top: 8px;
  font-family: 'SF Mono', Monaco, monospace;
}

/* ---- Pain point cards (5 mirror cats) ---- */
.pain-card {
  padding: 24px; border-radius: 12px; border: 1px solid;
  margin-bottom: 20px;
}
.pain-card .pain-head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 14px; gap: 16px; flex-wrap: wrap;
}
.pain-card .pain-title { font-size: 22px; font-weight: 700; margin: 0; }
.pain-card .pain-stat {
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 14px; font-weight: 700;
}
.pain-card .pain-sub { font-size: 14px; opacity: 0.85; margin: 0 0 14px; }
.pain-card h4 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px;
  margin: 14px 0 4px; color: rgba(0,0,0,0.6);
}
.pain-card p { margin: 4px 0 10px; }
.pain-card .pain-evidence { font-size: 12px; opacity: 0.7; }

/* ---- Recommendations ---- */
.rec {
  background: white; border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 22px; margin-bottom: 12px;
  border-left: 4px solid var(--gold);
}
.rec .rec-head { display: flex; gap: 10px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.rec .rec-title { font-weight: 700; font-size: 15px; color: var(--primary); }
.rec .rec-impact { color: var(--muted); font-size: 12px; }
.rec p { margin: 6px 0 0; font-size: 13px; }

/* ---- Trends ---- */
.trend {
  background: white; border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; margin-bottom: 10px;
}
.trend h4 { margin: 0 0 4px; font-size: 14px; color: var(--primary); }
.trend p { margin: 0; font-size: 13px; color: var(--ink); }

/* ---- Ticket browser ---- */
.filter-bar {
  display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center;
}
.filter-bar input, .filter-bar select {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px;
  font-size: 13px; font-family: inherit; min-width: 200px;
}
.filter-bar label { font-size: 12px; color: var(--muted); }
.browser-table { max-height: 70vh; overflow-y: auto; border-radius: 8px;
  border: 1px solid var(--border); }
.browser-table table { font-size: 12.5px; }
.browser-table th { position: sticky; top: 0; z-index: 2; }
"""


# ---- HTML body shell ----

def render_html(all_data: dict, options: list[tuple[str, str]],
                default_key: str) -> str:
    json_all = json.dumps(all_data, ensure_ascii=False, default=str)
    options_html = "\n".join(
        f'<option value="{html.escape(k)}">{html.escape(label)}</option>'
        for k, label in options
    )
    title = "AccessRP — User Feedback Insights"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>{CSS}</style>
</head>
<body>

<header class="hero">
  <div class="container">
    <div class="label">User Feedback Insights</div>
    <h1 id="reportTitle">AccessRP Helpdesk Insights</h1>
    <div class="subtitle">A stakeholder-friendly view of what is
    frustrating AccessRP users, which services need the most attention,
    and where the highest-impact improvements lie.</div>
    <div class="meta">Prepared for: Leadership &amp; Operations Teams
    &nbsp;•&nbsp; ADRES UX Analytics &nbsp;•&nbsp;
    {pd.Timestamp.now():%-d %B %Y}</div>

    <div class="month-picker">
      <label for="monthPicker">Reporting period</label>
      <select id="monthPicker">{options_html}</select>
    </div>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="label">Tickets Reviewed</div>
        <div class="value" id="kpi-total">—</div>
        <div class="delta" id="kpi-total-delta">—</div>
      </div>
      <div class="kpi-card">
        <div class="label">Distinct Issue Types</div>
        <div class="value" id="kpi-types">—</div>
        <div class="delta">Recurring user problems identified</div>
      </div>
      <div class="kpi-card">
        <div class="label">Top Pain Point</div>
        <div class="value" id="kpi-top-cat-pct">—</div>
        <div class="delta" id="kpi-top-cat-name">—</div>
      </div>
      <div class="kpi-card">
        <div class="label">Operational Noise</div>
        <div class="value" id="kpi-noise-pct">—</div>
        <div class="delta">Template emails &amp; routing artefacts</div>
      </div>
      <div class="kpi-card">
        <div class="label">Most Affected Service</div>
        <div class="value" id="kpi-svc-name">—</div>
        <div class="delta" id="kpi-svc-delta">—</div>
      </div>
    </div>
  </div>
</header>

<nav class="tabs">
  <div class="container">
    <button class="tab-btn active" data-tab="exec">Executive Summary</button>
    <button class="tab-btn" data-tab="topissues">Top Issues</button>
    <button class="tab-btn" data-tab="services">Most Affected Services</button>
    <button class="tab-btn" data-tab="distribution">Issue Distribution</button>
    <button class="tab-btn" data-tab="painpoints">Recurring Pain Points</button>
    <button class="tab-btn" data-tab="operational">Operational Issues</button>
    <button class="tab-btn" data-tab="trends">Key Trends</button>
    <button class="tab-btn" data-tab="recommendations">Recommendations</button>
    <button class="tab-btn" data-tab="browser">Ticket Browser</button>
  </div>
</nav>

<div class="container">

  <section id="exec" class="tab-content active">
    <h2>1. Executive Summary</h2>
    <p class="section-sub" id="execSub">A snapshot of the AccessRP helpdesk
    picture: where users are getting stuck, which services are taking the
    heaviest hit, and what the highest-impact moves look like.</p>
    <div class="grid-2">
      <div class="card">
        <h3>How users are getting stuck</h3>
        <div class="chart-container"><canvas id="painChart"></canvas></div>
      </div>
      <div class="card">
        <h3>Top 5 services by ticket volume</h3>
        <div class="chart-container"><canvas id="topSvcChart"></canvas></div>
      </div>
    </div>
    <div class="card" style="margin-top:18px;">
      <h3>The five things leadership should know</h3>
      <ol style="margin: 8px 0; padding-left: 22px; line-height: 1.9;" id="execBullets"></ol>
    </div>
  </section>

  <section id="topissues" class="tab-content">
    <h2>2. Top Issues Affecting Users</h2>
    <p class="section-sub">The 10 most frequent user-facing problems, ranked
    by volume. Each card explains what is happening, the pain category it
    belongs to, and provides example ticket IDs and a redacted user quote for
    verification.</p>
    <div id="topIssuesContainer"></div>
  </section>

  <section id="services" class="tab-content">
    <h2>3. Most Affected Services</h2>
    <p class="section-sub">The five AccessRP services receiving the heaviest
    support load, with the specific issues driving each.</p>
    <div id="topServicesContainer"></div>
  </section>

  <section id="distribution" class="tab-content">
    <h2>4. Issue Distribution Across Services</h2>
    <p class="section-sub">How user problems spread across different AccessRP
    services, with the share each pain category takes inside each service.</p>
    <div class="grid-2">
      <div class="card">
        <h3>Tickets per service</h3>
        <div class="chart-container tall"><canvas id="svcDistChart"></canvas></div>
      </div>
      <div class="card">
        <h3>Pain category mix per service</h3>
        <div class="chart-container tall"><canvas id="svcCatChart"></canvas></div>
      </div>
    </div>
    <div class="card" style="margin-top:18px;">
      <h3>Full breakdown</h3>
      <div id="svcCatTable"></div>
    </div>
  </section>

  <section id="painpoints" class="tab-content">
    <h2>5. Recurring User Pain Points</h2>
    <p class="section-sub">The five recurring patterns that explain why users
    are frustrated. Each card includes the underlying behaviour, why it is
    happening, what would fix it, and example ticket IDs.</p>
    <div id="painCardsContainer"></div>
  </section>

  <section id="operational" class="tab-content">
    <h2>6. Critical Operational Issues</h2>
    <p class="section-sub">Issues that are not user pain points per se, but
    distort operational metrics and create avoidable workload for the support
    team. Reducing these makes the rest of the dashboard more honest.</p>
    <div id="operationalContainer"></div>
  </section>

  <section id="trends" class="tab-content">
    <h2>7. Key Trends &amp; Observations</h2>
    <p class="section-sub">High-level patterns worth surfacing to leadership
    in addition to the headline metrics.</p>
    <div id="trendsContainer"></div>
  </section>

  <section id="recommendations" class="tab-content">
    <h2>8. Recommendations &amp; Opportunities</h2>
    <p class="section-sub">Prioritised actions linked to the underlying pain
    points, with addressable-ticket counts as a rough sizing.</p>
    <div id="recommendationsContainer"></div>
  </section>

  <section id="browser" class="tab-content">
    <h2>9. Ticket Browser</h2>
    <p class="section-sub" id="browserSub">Search and filter the tickets for
    the selected reporting period. Useful for verifying any finding or pulling
    representative examples for a stakeholder discussion. Quotes are
    redacted.</p>
    <div class="filter-bar">
      <div>
        <label>Search</label><br>
        <input type="text" id="browserSearch" placeholder="search subject, body, theme...">
      </div>
      <div>
        <label>Pain Category</label><br>
        <select id="browserCat">
          <option value="">All categories</option>
        </select>
      </div>
      <div>
        <label>Service</label><br>
        <select id="browserSvc">
          <option value="">All services</option>
        </select>
      </div>
      <div>
        <span id="browserCount" style="font-weight:600;color: var(--primary);"></span>
      </div>
    </div>
    <div class="browser-table">
      <table>
        <thead><tr>
          <th style="width: 70px;">ID</th>
          <th style="width: 140px;">Service</th>
          <th style="width: 150px;">Issue</th>
          <th style="width: 150px;">Pain Category</th>
          <th>Subject / Quote (redacted)</th>
        </tr></thead>
        <tbody id="browserBody"></tbody>
      </table>
    </div>
  </section>

  <p style="color: var(--muted); font-size: 12px; margin-top: 40px;
            padding-top: 18px; border-top: 1px solid var(--border);">
    <strong>Methodology.</strong> Source data: AccessRP Freshdesk export for the
    period covered. Tickets in the &ldquo;Ads Test Tickets and Auto-Emails&rdquo;
    service and tickets matching auto-reply / delivery-failure /
    submission-confirmation patterns are excluded.
    Themes are detected via a bilingual rule-based classifier (English + Arabic
    keywords). Quotes are PII-redacted (emails, phones, EIDs, application
    reference numbers, unit / licence / passport numbers, URLs).
    Generated {pd.Timestamp.now():%Y-%m-%d}. Source:
    <a href="https://github.com/ymedhatadres/accessrp-dashboard"
       style="color: var(--primary);">accessrp-dashboard</a>.
  </p>
</div>

<script>
const ALL_DATA = {json_all};
const DEFAULT_MONTH = "{html.escape(default_key)}";
{RENDERER_JS}
</script>
</body>
</html>"""


RENDERER_JS = r"""
// ---- Tab nav (static, doesn't depend on month) ----
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const id = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.toggle('active', s.id === id));
    setHash('#' + id);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
});

let DATA = null;
const charts = {};

function destroyCharts() {
  for (const k of Object.keys(charts)) {
    try { charts[k] && charts[k].destroy(); } catch(e) {}
    delete charts[k];
  }
}
function clearAllDynamic() {
  ['execBullets','topIssuesContainer','topServicesContainer','svcCatTable',
   'painCardsContainer','operationalContainer','trendsContainer',
   'recommendationsContainer','browserBody'].forEach(id => {
     const el = document.getElementById(id);
     if (el) el.innerHTML = '';
  });
  // Reset browser dropdowns to their default-only options
  const catSel = document.getElementById('browserCat');
  const svcSel = document.getElementById('browserSvc');
  if (catSel) catSel.innerHTML = '<option value="">All categories</option>';
  if (svcSel) svcSel.innerHTML = '<option value="">All services</option>';
}

function setHash(h) {
  const u = new URL(location.href);
  u.hash = h.startsWith('#') ? h.substring(1) : h;
  history.replaceState(null, '', u.toString());
}
function setMonthParam(m) {
  const u = new URL(location.href);
  u.searchParams.set('m', m);
  history.replaceState(null, '', u.toString());
}

function renderHero() {
  const pc = DATA.pain_categories;
  const topCat = pc[DATA.top_cat_key];
  const topSvcName = (DATA.top_services[0] || ['—', 0])[0];
  const topSvcN = (DATA.top_services[0] || ['—', 0])[1];
  const topSvcPct = DATA.total ? (topSvcN / DATA.total * 100) : 0;

  document.getElementById('reportTitle').textContent =
    'AccessRP Helpdesk Insights — ' + DATA.period;
  document.title = 'AccessRP — User Feedback Insights (' + DATA.period + ')';

  document.getElementById('kpi-total').textContent = DATA.total.toLocaleString();
  document.getElementById('kpi-total-delta').textContent =
    DATA.period + ' helpdesk volume';
  document.getElementById('kpi-types').textContent = DATA.all_issues.length;
  document.getElementById('kpi-top-cat-pct').textContent =
    DATA.top_cat_share.toFixed(1) + '%';
  document.getElementById('kpi-top-cat-name').textContent = topCat.title;
  document.getElementById('kpi-noise-pct').textContent =
    DATA.op_noise_share.toFixed(1) + '%';
  document.getElementById('kpi-svc-name').textContent = topSvcName;
  document.getElementById('kpi-svc-delta').textContent =
    topSvcN.toLocaleString() + ' tickets (' + topSvcPct.toFixed(0) + '% of total)';

  document.getElementById('execSub').textContent =
    'A snapshot of the AccessRP helpdesk picture for ' + DATA.period +
    ': where users are getting stuck, which services are taking the heaviest hit, and what the highest-impact moves look like.';
  document.getElementById('browserSub').textContent =
    'Search and filter the ' + DATA.total.toLocaleString() +
    ' tickets in ' + DATA.period + '. Useful for verifying any finding or pulling representative examples. Quotes are redacted.';
}

function renderAll(monthKey) {
  DATA = ALL_DATA[monthKey];
  destroyCharts();
  clearAllDynamic();
  renderHero();

  const catKeys = Object.keys(DATA.pain_categories);
  const catColor = k => DATA.pain_categories[k].color;
  const catTitle = k => DATA.pain_categories[k].title;

// ---- Exec: doughnut ----
charts.pain = new Chart(document.getElementById('painChart'), {
  type: 'doughnut',
  data: {
    labels: catKeys.map(catTitle),
    datasets: [{
      data: catKeys.map(k => DATA.cat_counts[k] || 0),
      backgroundColor: catKeys.map(catColor),
      borderWidth: 2, borderColor: '#fff',
    }],
  },
  options: {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { position: 'right', labels: { font: { size: 12 }, boxWidth: 14, padding: 10 } },
      tooltip: { callbacks: { label: ctx => {
        const pct = (ctx.parsed / DATA.total * 100).toFixed(1);
        return `${ctx.label}: ${ctx.parsed} tickets (${pct}%)`;
      } } }
    }
  }
});

// ---- Exec: top 5 services bar ----
charts.topSvc = new Chart(document.getElementById('topSvcChart'), {
  type: 'bar',
  data: {
    labels: DATA.top_services.map(s => s[0]),
    datasets: [{ label: 'Tickets', data: DATA.top_services.map(s => s[1]), backgroundColor: '#0F2D3D' }],
  },
  options: {
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { x: { beginAtZero: true } },
  }
});

// ---- Exec bullets ----
{
  const ol = document.getElementById('execBullets');
  const sortedCats = catKeys.slice().sort((a,b) => (DATA.cat_counts[b]||0) - (DATA.cat_counts[a]||0));
  const top1 = sortedCats[0], top2 = sortedCats[1];
  const top1Cfg = DATA.pain_categories[top1];
  const topIssue = DATA.top_user_issues[0];
  const topSvc = DATA.top_services[0];
  const bullets = [
    `<strong>${top1Cfg.title} is the largest pain category.</strong> ${DATA.cat_counts[top1]} tickets (${(DATA.cat_counts[top1]/DATA.total*100).toFixed(0)}% of total). ${top1Cfg.subtitle}`,
    `<strong>The single most-reported issue is "${topIssue.name}"</strong> with ${topIssue.count} tickets (${topIssue.pct.toFixed(1)}%). ${topIssue.description}`,
    `<strong>${topSvc[0]} carries ${topSvc[1]} tickets</strong> — ${(topSvc[1]/DATA.total*100).toFixed(0)}% of all complaints flow through this one service. Improvements here have the highest immediate volume impact.`,
    `<strong>${DATA.pain_categories[top2].title} comes second.</strong> ${DATA.cat_counts[top2]} tickets. ${DATA.pain_categories[top2].subtitle}`,
    `<strong>Self-service gaps are the biggest deflection opportunity.</strong> ${DATA.cat_counts.self_service||0} tickets are users asking the helpdesk to perform an action a self-serve UI could perform.`,
  ];
  bullets.forEach(b => { const li = document.createElement('li'); li.innerHTML = b; ol.appendChild(li); });
}

// ---- Top issues cards ----
{
  const el = document.getElementById('topIssuesContainer');
  DATA.top_user_issues.forEach((issue, i) => {
    const cat = DATA.pain_categories[issue.category];
    const div = document.createElement('div');
    div.className = 'issue-card';
    div.innerHTML = `
      <div class="rank-circle" style="background: ${cat.color}22; color: ${cat.color};">${i+1}</div>
      <div class="issue-body">
        <div class="issue-meta">
          <span class="pill cat-${issue.category}">${cat.title}</span>
          <strong>${issue.count} tickets</strong>
          <span style="color: var(--muted);">(${issue.pct.toFixed(1)}% of all)</span>
        </div>
        <h4 class="issue-name">${issue.name}</h4>
        <div class="issue-desc">${issue.description}</div>
        ${issue.sample_quote ? `<div class="quote">"${issue.sample_quote}" <br/><span class="ticket-id">— Ticket ${issue.sample_quote_id}</span></div>` : ''}
        <div class="issue-evidence">Sample tickets: ${issue.samples.map(id => '#'+id).join(', ')}</div>
      </div>
    `;
    el.appendChild(div);
  });
}

// ---- Top services cards ----
{
  const el = document.getElementById('topServicesContainer');
  Object.entries(DATA.top_service_issues).forEach(([svc, info]) => {
    const div = document.createElement('div');
    div.className = 'card';
    div.style.marginBottom = '14px';
    const rows = info.top_issues.map(iss => {
      const cat = DATA.pain_categories[iss.category];
      return `
        <div style="padding: 10px 0; border-bottom: 1px dashed var(--border);">
          <div style="display:flex;gap:10px;align-items:center;margin-bottom:4px;flex-wrap:wrap;">
            <span class="pill cat-${iss.category}">${cat.title}</span>
            <strong>${iss.name}</strong>
            <span style="color: var(--muted);">${iss.count} tickets</span>
          </div>
          ${iss.sample_quote ? `<div class="quote">"${iss.sample_quote}" <br/><span class="ticket-id">— Ticket ${iss.sample_quote_id}</span></div>` : ''}
        </div>
      `;
    }).join('');
    div.innerHTML = `
      <h3>${svc} <span style="color: var(--muted); font-weight:400; font-size: 14px;">— ${info.total} tickets · ${info.users} users · avg sentiment ${info.avg_sentiment ?? '—'}</span></h3>
      ${rows}
      <div class="issue-evidence" style="margin-top: 10px;">Sample tickets: ${info.samples.map(id => '#'+id).join(', ')}</div>
    `;
    el.appendChild(div);
  });
}

// ---- Distribution: tickets per service ----
charts.svcDist = new Chart(document.getElementById('svcDistChart'), {
  type: 'bar',
  data: {
    labels: DATA.all_services.map(s => s[0]),
    datasets: [{ data: DATA.all_services.map(s => s[1]), backgroundColor: '#0F2D3D' }],
  },
  options: {
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { x: { beginAtZero: true } },
  }
});

// ---- Distribution: pain category mix per service (stacked) ----
charts.svcCat = new Chart(document.getElementById('svcCatChart'), {
  type: 'bar',
  data: {
    labels: DATA.service_category_table.map(r => r.service),
    datasets: catKeys.map(k => ({
      label: DATA.pain_categories[k].title,
      data: DATA.service_category_table.map(r => r.breakdown[k] || 0),
      backgroundColor: DATA.pain_categories[k].color,
    })),
  },
  options: {
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    scales: { x: { stacked: true, beginAtZero: true }, y: { stacked: true } },
    plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } },
  }
});

// ---- Distribution table ----
{
  const el = document.getElementById('svcCatTable');
  let html = '<table><thead><tr><th>Service</th><th class="num">Total</th>';
  catKeys.forEach(k => html += `<th class="num">${DATA.pain_categories[k].title}</th>`);
  html += '</tr></thead><tbody>';
  DATA.service_category_table.forEach(r => {
    html += `<tr><td><strong>${r.service}</strong></td><td class="num">${r.total}</td>`;
    catKeys.forEach(k => html += `<td class="num">${r.breakdown[k] || 0}</td>`);
    html += '</tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

// ---- Pain point cards ----
{
  const el = document.getElementById('painCardsContainer');
  DATA.pain_points.forEach(p => {
    const div = document.createElement('div');
    div.className = 'pain-card';
    div.style.background = p.bg;
    div.style.borderColor = p.color + '55';
    div.style.color = '#222';
    div.innerHTML = `
      <div class="pain-head">
        <h3 class="pain-title" style="color: ${p.color};">${p.title}</h3>
        <div class="pain-stat" style="color: ${p.color};">${p.count} tickets · ${p.pct.toFixed(1)}%</div>
      </div>
      <p class="pain-sub">${p.subtitle}</p>
      <h4>What is happening</h4><p>${p.why}</p>
      <h4>What would fix it</h4><p>${p.fix}</p>
      ${p.sample_quote ? `<div class="quote">"${p.sample_quote}" <br/><span class="ticket-id">— Ticket ${p.sample_quote_id}</span></div>` : ''}
      <div class="pain-evidence">Sample tickets: ${p.samples.map(id => '#'+id).join(', ')}</div>
    `;
    el.appendChild(div);
  });
}

// ---- Operational issues ----
{
  const el = document.getElementById('operationalContainer');
  DATA.operational_issues.forEach(o => {
    const div = document.createElement('div');
    div.className = 'card';
    div.style.marginBottom = '12px';
    div.innerHTML = `
      <h3>${o.name} <span style="color: var(--muted); font-weight:400; font-size: 13px;">— ${o.count} tickets</span></h3>
      <p>${o.description}</p>
      <div class="issue-evidence">Sample tickets: ${o.samples.map(id => '#'+id).join(', ')}</div>
    `;
    el.appendChild(div);
  });
}

// ---- Trends ----
{
  const el = document.getElementById('trendsContainer');
  DATA.trends.forEach(t => {
    const div = document.createElement('div');
    div.className = 'trend';
    div.innerHTML = `<h4>${t.title}</h4><p>${t.detail}</p>`;
    el.appendChild(div);
  });
}

// ---- Recommendations ----
{
  const el = document.getElementById('recommendationsContainer');
  DATA.recommendations.forEach(r => {
    const cat = DATA.pain_categories[r.category_key];
    const div = document.createElement('div');
    div.className = 'rec';
    div.innerHTML = `
      <div class="rec-head">
        <span class="pill priority-${r.priority.toLowerCase()}">${r.priority} priority</span>
        <span class="pill cat-${r.category_key}">${cat ? cat.title : ''}</span>
        <span class="rec-title">${r.title}</span>
        <span class="rec-impact">${r.impact_text}</span>
      </div>
      <p>${r.rationale}</p>
    `;
    el.appendChild(div);
  });
}

// ---- Ticket browser ----
{
  const cats = new Set(DATA.tickets.map(t => t.category));
  const svcs = new Set(DATA.tickets.map(t => t.s));
  const catSel = document.getElementById('browserCat');
  const svcSel = document.getElementById('browserSvc');
  [...cats].sort().forEach(c => { const o = document.createElement('option'); o.value = c; o.text = c; catSel.appendChild(o); });
  [...svcs].sort().forEach(s => { const o = document.createElement('option'); o.value = s; o.text = s; svcSel.appendChild(o); });

  const body = document.getElementById('browserBody');
  const count = document.getElementById('browserCount');
  const search = document.getElementById('browserSearch');
  function renderBrowser() {
    const q = (search.value || '').toLowerCase();
    const c = catSel.value, s = svcSel.value;
    const rows = DATA.tickets.filter(t => {
      if (c && t.category !== c) return false;
      if (s && t.s !== s) return false;
      if (q) {
        const hay = (t.sub + ' ' + t.q + ' ' + t.issue).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    count.textContent = `${rows.length.toLocaleString()} of ${DATA.tickets.length.toLocaleString()} tickets`;
    body.innerHTML = rows.slice(0, 500).map(t => `
      <tr>
        <td class="ticket-id">#${t.id}</td>
        <td>${t.s}</td>
        <td>${t.issue}</td>
        <td><span class="pill cat-${t.category_key}">${t.category}</span></td>
        <td><div style="font-weight:600;">${t.sub}</div><div style="color: var(--muted); font-style:italic; margin-top: 4px;">${t.q}</div></td>
      </tr>
    `).join('');
  }
  // Avoid stacking listeners on every renderAll — clone the inputs.
  const newSearch = search.cloneNode(true); search.parentNode.replaceChild(newSearch, search);
  const newCatSel = catSel.cloneNode(false);
  newCatSel.appendChild(document.createElement('option'));
  newCatSel.firstChild.value = ''; newCatSel.firstChild.text = 'All categories';
  [...cats].sort().forEach(c => { const o = document.createElement('option'); o.value = c; o.text = c; newCatSel.appendChild(o); });
  catSel.parentNode.replaceChild(newCatSel, catSel);
  const newSvcSel = svcSel.cloneNode(false);
  newSvcSel.appendChild(document.createElement('option'));
  newSvcSel.firstChild.value = ''; newSvcSel.firstChild.text = 'All services';
  [...svcs].sort().forEach(s => { const o = document.createElement('option'); o.value = s; o.text = s; newSvcSel.appendChild(o); });
  svcSel.parentNode.replaceChild(newSvcSel, svcSel);
  newSearch.addEventListener('input', renderBrowser);
  newCatSel.addEventListener('change', renderBrowser);
  newSvcSel.addEventListener('change', renderBrowser);
  renderBrowser();
}
}  // end renderAll

// ---- Initial wiring ----
{
  const picker = document.getElementById('monthPicker');
  const urlM = new URLSearchParams(location.search).get('m');
  const initial = (urlM && ALL_DATA[urlM]) ? urlM : DEFAULT_MONTH;
  picker.value = initial;
  picker.addEventListener('change', e => {
    renderAll(e.target.value);
    setMonthParam(e.target.value);
  });
  renderAll(initial);
  // Restore tab from URL hash, if any.
  if (location.hash) {
    const h = location.hash.replace('#','');
    const btn = document.querySelector(`.tab-btn[data-tab="${h}"]`);
    if (btn) btn.click();
  }
}
"""


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="default month to open the report on, e.g. '2026-05'")
    args = parser.parse_args()

    all_data, options, default_key = build_all_months()
    if args.month:
        if args.month not in all_data:
            avail = [k for k, _ in options]
            raise SystemExit(f"No data for month '{args.month}'. Available: {avail}")
        default_key = args.month

    months_with_data = [k for k, _ in options if k != "all"]
    total_all = all_data["all"]["total"]
    print(f"Embedding {len(months_with_data)} months + 'all' view "
          f"(total {total_all:,} real complaints). Default tab: {default_key}.")

    html_str = render_html(all_data, options, default_key)

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html_str, encoding="utf-8")
    print(f"Wrote {OUT_HTML}  ({OUT_HTML.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
