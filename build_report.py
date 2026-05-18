"""Generate the static UX-research HTML report for AccessRP.

Defaults to April 2026 (Q2). Output: docs/index.html — a single
self-contained file safe to publish via GitHub Pages, with PII in
embedded quotes redacted.

Usage:
    python3 build_report.py                       # April 2026
    python3 build_report.py --quarter "2026 Q1"   # full Q1
    python3 build_report.py --all                 # everything
"""

from __future__ import annotations

import argparse
import html
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
# PII redaction — applied to every quote before it's embedded in the report.
# Ticket IDs (small integers) are intentionally NOT redacted; they're
# meaningless without internal Freshdesk access.
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
# Theme -> high-level issue category mapping
# ----------------------------------------------------------------------------

CATEGORY_MAP = {
    "Login / Access": "Access",
    "Payment / Wallet": "Payment",
    "Application stuck / pending": "Technical",
    "Application not found / missing": "Technical",
    "Rejection / declined": "Business / Process",
    "Cancellation request": "Business / Process",
    "Data correction / update": "Data",
    "Document / attachment issue": "Documentation",
    "Certificate": "Business / Process",
    "Lease / tenancy": "Business / Process",
    "Transfer / POA": "Business / Process",
    "Appointment / booking": "UX",
    "Error / system issue": "Technical",
    "Slow / performance": "Technical",
    "Arabic-language ticket": "Language / UX",
}

THEME_KEYWORDS = {
    "Login / Access": ["login", "log in", "sign in", "otp", "password", "access"],
    "Payment / Wallet": ["payment", "wallet", "top up", "refund", "deduct",
                          "charge", "paid"],
    "Application stuck / pending": ["stuck", "pending", "waiting", "under review"],
    "Application not found / missing": ["not found", "missing", "cannot find"],
    "Rejection / declined": ["rejected", "declined", "denied"],
    "Cancellation request": ["cancel", "withdraw"],
    "Data correction / update": ["update", "wrong", "incorrect", "amend", "change"],
    "Document / attachment issue": ["document", "attachment", "upload", "pdf"],
    "Certificate": ["certificate", "noc"],
    "Lease / tenancy": ["lease", "tenancy", "tenant", "ejari", "pma"],
    "Transfer / POA": ["transfer", "poa", "power of attorney"],
    "Appointment / booking": ["appointment", "booking", "reschedule"],
    "Error / system issue": ["error", "failed", "broken", "something went wrong"],
    "Slow / performance": ["slow", "loading", "timeout"],
    "Arabic-language ticket": [],
}

# Strategic recommendations keyed to themes (richer than the in-app suggestions
# since this lives in a one-shot report).
RECOMMENDATIONS = {
    "Data correction / update": (
        "Build self-serve data-correction inside AccessRP",
        "20%+ of helpdesk volume is users asking back-office staff to edit "
        "fields they should be able to edit themselves (email, phone, license "
        "details, owner info). A first-class 'Modify my information' flow "
        "would deflect a large share of tickets immediately.",
        "High",
    ),
    "Payment / Wallet": (
        "Audit payment-to-receipt pipeline and add duplicate-payment guards",
        "Recurring pattern of 'I paid but the system still asks me to pay' or "
        "'money deducted, no receipt issued'. Investigate the gateway → "
        "ledger → application-status handoff and surface a self-serve "
        "payment-status / refund page.",
        "High",
    ),
    "Transfer / POA": (
        "Replace email-based appointment booking with a proper in-product form",
        "A meaningful chunk of Transfer-of-Interest tickets are structured "
        "form submissions sent over email because no UI exists. Build an "
        "in-product booking flow with calendar slots and instant confirmation.",
        "High",
    ),
    "Appointment / booking": (
        "Build self-serve appointment booking + rescheduling",
        "Currently users email support to request, reschedule, or cancel "
        "appointments. A simple booking widget would deflect these and give "
        "users faster certainty.",
        "Medium",
    ),
    "Lease / tenancy": (
        "Make business rules visible inside the lease service",
        "Users consistently lack awareness of rules like the 90-day automatic "
        "contract closure after expiry. Surface these rules in the service "
        "card BEFORE the user starts a flow, not after they're blocked.",
        "Medium",
    ),
    "Error / system issue": (
        "Categorise 'something went wrong' errors and add structured logging",
        "Generic error messages are driving ticket volume because users can't "
        "self-diagnose. Add reference codes to error states and route the "
        "most-common errors to specific help content.",
        "High",
    ),
    "Application stuck / pending": (
        "Make application status and ETA visible to the user",
        "Users raise tickets because they have no visibility into where their "
        "application is in the workflow. Expose stage + expected duration in "
        "the application page; alert internally when items idle > N days.",
        "Medium",
    ),
    "Document / attachment issue": (
        "Audit upload limits, file-type support, and PDF generation",
        "Repeated complaints about uploads failing or generated documents "
        "being missing/wrong. Review the document pipeline end-to-end.",
        "Medium",
    ),
    "Certificate": (
        "Improve certificate / NOC generation reliability and visibility",
        "Users follow up because they can't tell whether the certificate was "
        "issued. Make status explicit and surface ETA.",
        "Medium",
    ),
    "Rejection / declined": (
        "Surface clearer rejection reasons and a guided re-submission flow",
        "Vague rejection wording leads to appeal tickets. Make rejection "
        "reasons specific and actionable inside the app.",
        "Medium",
    ),
    "Cancellation request": (
        "Add self-serve cancel for safe application types",
        "Many cancellations are routine and don't need human review. Build "
        "the user-facing cancel button and a clear cancel SLA for the rest.",
        "Low",
    ),
    "Login / Access": (
        "Review OTP delivery and improve login error messaging",
        "Most access tickets cluster around OTP/credential issues. Audit "
        "provider reliability and replace generic error states with concrete "
        "next steps.",
        "Medium",
    ),
    "Arabic-language ticket": (
        "Ensure Arabic-speaking users have parity in self-serve flows",
        "Many Arabic-language tickets repeat patterns also seen in English. "
        "Verify the Arabic UI exposes the same self-serve options to avoid "
        "duplicating support load.",
        "Medium",
    ),
}


# ----------------------------------------------------------------------------
# Data prep
# ----------------------------------------------------------------------------


def load_period(quarter: str | None, all_data: bool) -> tuple[pd.DataFrame, str]:
    df = pd.read_parquet(PARQUET)
    df = classify(df)
    df = df.loc[~df["is_noise"]].reset_index(drop=True)

    if all_data:
        return df, f"{df['created_at'].min():%b %Y} – {df['created_at'].max():%b %Y}"
    if quarter:
        sub = df[df["quarter"] == quarter].reset_index(drop=True)
        return sub, quarter
    # default: latest available quarter
    latest = sorted(df["quarter"].dropna().unique())[-1]
    sub = df[df["quarter"] == latest].reset_index(drop=True)
    period = (
        f"April 2026" if latest == "2026 Q2"
        else f"{sub['created_at'].min():%b %Y} – {sub['created_at'].max():%b %Y}"
    )
    return sub, period


def pick_quotes(df: pd.DataFrame, theme: str, k: int = 3) -> list[dict]:
    """Pick k representative quotes, redacted, with ticket IDs."""
    kw = THEME_KEYWORDS.get(theme, [])
    cand = (
        df[df["description_text"].notna()]
        .sort_values("sentiment_score", ascending=True, na_position="last")
        .head(50)
        .copy()
    )
    cand["clean"] = cand["description_text"].map(clean_description)
    cand = cand[cand["clean"].str.len() > 30]
    out: list[dict] = []
    seen: set[str] = set()
    for _, r in cand.iterrows():
        salient = extract_sentences(r["clean"], kw)
        if not salient or len(salient) < 25:
            continue
        red = redact(salient)[:320]
        if red in seen:
            continue
        seen.add(red)
        out.append({
            "id": int(r["id"]),
            "service": r.get("custom_fields.cf_service") or "—",
            "text": red,
        })
        if len(out) >= k:
            break
    return out


def theme_rows(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for theme in CATEGORY_MAP:
        mask = df["themes_list"].apply(lambda lst, t=theme: t in (lst or []))
        sub = df[mask]
        if sub.empty:
            continue
        rows.append({
            "theme": theme,
            "category": CATEGORY_MAP[theme],
            "tickets": len(sub),
            "users": sub["requester.email"].nunique(),
            "avg_sent": sub["sentiment_score"].mean(),
            "top_services": sub["custom_fields.cf_service"].dropna().value_counts().head(3).index.tolist(),
            "sample_ids": sub.sort_values("sentiment_score").head(3)["id"].astype(int).tolist(),
        })
    return pd.DataFrame(rows).sort_values("tickets", ascending=False).reset_index(drop=True)


def service_rows(df: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    rows = []
    svc_col = "custom_fields.cf_service"
    top_services = df[svc_col].dropna().value_counts().head(k).index.tolist()
    for svc in top_services:
        sub = df[df[svc_col] == svc]
        if sub.empty:
            continue
        # top themes within this service
        all_themes = []
        for _lst in sub["themes_list"]:
            for t in (_lst or []):
                if t in CATEGORY_MAP:
                    all_themes.append(t)
        top_themes = Counter(all_themes).most_common(4)
        rows.append({
            "service": svc,
            "tickets": len(sub),
            "users": sub["requester.email"].nunique(),
            "avg_sent": sub["sentiment_score"].mean(),
            "top_themes": top_themes,
            "sample_ids": sub.sort_values("sentiment_score").head(3)["id"].astype(int).tolist(),
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# HTML rendering helpers
# ----------------------------------------------------------------------------

def E(s) -> str:
    """HTML-escape any string-able value."""
    return html.escape("" if s is None else str(s))


def ticket_chips(ids: list[int]) -> str:
    return " ".join(f'<span class="chip">#{i}</span>' for i in ids[:6])


def quote_block(quotes: list[dict]) -> str:
    if not quotes:
        return '<p class="muted">No representative quotes available.</p>'
    parts = []
    for q in quotes:
        parts.append(
            f'<blockquote>'
            f'<p>{E(q["text"])}</p>'
            f'<footer>Ticket <strong>#{q["id"]}</strong> · {E(q["service"])}</footer>'
            f'</blockquote>'
        )
    return "\n".join(parts)


def bar_row(label: str, value: int, max_value: int, count_suffix: str = "") -> str:
    pct = (value / max_value * 100) if max_value else 0
    return (
        f'<div class="bar-row">'
        f'<div class="bar-label">{E(label)}</div>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>'
        f'<div class="bar-value">{value:,}{count_suffix}</div>'
        f'</div>'
    )


# ----------------------------------------------------------------------------
# Main rendering
# ----------------------------------------------------------------------------

CSS = """
:root {
  --navy: #0F2D3D;
  --gold: #B89968;
  --cream: #FAF7F0;
  --ink: #1A1A1A;
  --muted: #6B6B6B;
  --border: #E5E0D2;
  --red: #B85C5C;
  --green: #5A8C5C;
  --shadow: 0 2px 6px rgba(15, 45, 61, 0.06);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--cream); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.55;
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 2.4rem 1.6rem 6rem; }
.serif { font-family: Georgia, 'Times New Roman', serif; }

/* ---- Header ---- */
.report-header {
  border-left: 6px solid var(--gold);
  padding: 0.4rem 0 0.4rem 1rem;
  margin-bottom: 1.8rem;
}
.report-header h1 {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 2.2rem; color: var(--navy); margin: 0 0 0.3rem 0;
  letter-spacing: -0.01em;
}
.report-header .meta {
  color: var(--muted); font-size: 0.92rem; font-style: italic;
}

/* ---- KPI strip ---- */
.kpi-strip {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 1rem; margin: 1.5rem 0 2rem;
}
.kpi {
  background: white; border: 1px solid var(--border);
  border-left: 4px solid var(--gold); padding: 0.9rem 1.1rem;
  border-radius: 4px; box-shadow: var(--shadow);
}
.kpi .label {
  color: var(--muted); font-size: 0.72rem; letter-spacing: 0.08em;
  text-transform: uppercase; font-weight: 600;
}
.kpi .value {
  font-family: Georgia, serif; color: var(--navy);
  font-size: 1.85rem; font-weight: 700; margin-top: 0.25rem;
}
.kpi .sub { color: var(--muted); font-size: 0.82rem; margin-top: 0.15rem; }

/* ---- TOC ---- */
.toc {
  background: white; border: 1px solid var(--border); border-radius: 6px;
  padding: 1rem 1.3rem; margin-bottom: 2.4rem;
}
.toc h3 {
  margin: 0 0 0.6rem; font-size: 0.78rem; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--muted); font-weight: 700;
}
.toc ol {
  margin: 0; padding-left: 1.2rem; columns: 2; column-gap: 2.5rem;
}
.toc li { margin: 0.18rem 0; }
.toc a { color: var(--navy); text-decoration: none; font-weight: 500; }
.toc a:hover { color: var(--gold); }

/* ---- Section ---- */
section {
  background: white; border: 1px solid var(--border); border-radius: 6px;
  padding: 1.6rem 1.8rem; margin-bottom: 1.6rem; box-shadow: var(--shadow);
  scroll-margin-top: 1rem;
}
section h2 {
  font-family: Georgia, serif; color: var(--navy); margin: 0 0 0.4rem;
  font-size: 1.55rem; border-bottom: 2px solid var(--gold);
  padding-bottom: 0.5rem; display: inline-block;
}
section h3 {
  color: var(--navy); font-size: 1.15rem; margin: 1.4rem 0 0.4rem;
  font-weight: 700;
}
section h4 {
  color: var(--navy); font-size: 1rem; margin: 1.1rem 0 0.3rem;
  font-weight: 700;
}
section p, section li { color: var(--ink); }
.muted { color: var(--muted); }

/* ---- Tables ---- */
table {
  width: 100%; border-collapse: collapse; margin: 0.6rem 0;
  font-size: 0.92rem;
}
th, td {
  text-align: left; padding: 0.55rem 0.7rem;
  border-bottom: 1px solid var(--border);
}
th {
  background: var(--cream); color: var(--navy); font-weight: 700;
  font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase;
}
td.num { text-align: right; font-variant-numeric: tabular-nums; }

/* ---- Pain point cards ---- */
.pain {
  border: 1px solid var(--border); border-left: 3px solid var(--gold);
  padding: 0.9rem 1.1rem; margin: 0.8rem 0; border-radius: 4px;
  background: #fdfcf7;
}
.pain .title { font-weight: 700; color: var(--navy); font-size: 1.05rem; }
.pain .stats {
  color: var(--muted); font-size: 0.82rem; margin: 0.2rem 0 0.4rem;
}
.pain p { margin: 0.35rem 0; }

/* ---- Critical issues ---- */
.critical {
  display: grid; grid-template-columns: 60px 1fr; gap: 0.8rem;
  border: 1px solid var(--border); border-radius: 4px;
  padding: 1rem 1.1rem; margin: 0.8rem 0; background: white;
}
.critical .rank {
  font-family: Georgia, serif; font-size: 1.9rem; font-weight: 700;
  color: var(--gold); text-align: center; line-height: 1;
  border-right: 1px solid var(--border); padding-right: 0.8rem;
  display: flex; align-items: center; justify-content: center;
}
.critical .body .title {
  font-weight: 700; color: var(--navy); font-size: 1.08rem;
}
.critical .body .why {
  color: var(--ink); margin: 0.4rem 0 0.5rem; font-size: 0.95rem;
}
.critical .body .stats { color: var(--muted); font-size: 0.82rem; }

/* ---- Chips ---- */
.chip {
  display: inline-block; background: var(--cream); border: 1px solid var(--border);
  color: var(--navy); padding: 0.15rem 0.5rem; border-radius: 99px;
  font-size: 0.78rem; font-weight: 600; margin-right: 0.25rem;
  font-variant-numeric: tabular-nums;
}
.badge {
  display: inline-block; padding: 0.15rem 0.55rem; border-radius: 4px;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
  text-transform: uppercase;
}
.badge.high   { background: #fce8e8; color: var(--red); }
.badge.med    { background: #fff4d9; color: #8a6a00; }
.badge.medium { background: #fff4d9; color: #8a6a00; }
.badge.low    { background: #e7f0e7; color: var(--green); }

/* ---- Quotes ---- */
blockquote {
  margin: 0.6rem 0; padding: 0.7rem 0.9rem; background: var(--cream);
  border-left: 3px solid var(--gold); border-radius: 3px;
}
blockquote p { margin: 0 0 0.3rem; font-style: italic; color: var(--ink); }
blockquote footer {
  color: var(--muted); font-size: 0.82rem; font-style: normal;
}
blockquote footer strong { color: var(--navy); }

/* ---- Bar chart ---- */
.bar-row {
  display: grid; grid-template-columns: 220px 1fr 70px;
  gap: 0.8rem; align-items: center; margin: 0.35rem 0;
}
.bar-label { font-size: 0.9rem; color: var(--navy); font-weight: 500; }
.bar-track {
  background: var(--cream); border: 1px solid var(--border); border-radius: 3px;
  height: 18px; overflow: hidden;
}
.bar-fill { height: 100%; background: var(--gold); transition: width .3s; }
.bar-value {
  text-align: right; font-variant-numeric: tabular-nums;
  color: var(--navy); font-weight: 600; font-size: 0.88rem;
}

/* ---- Recommendation rows ---- */
.rec {
  border: 1px solid var(--border); border-left: 3px solid var(--navy);
  padding: 0.9rem 1.1rem; margin: 0.7rem 0; background: white;
  border-radius: 4px;
}
.rec .head { display: flex; align-items: center; gap: 0.6rem; }
.rec .head .title { font-weight: 700; color: var(--navy); font-size: 1.02rem; }
.rec .why { margin: 0.5rem 0; color: var(--ink); }

/* ---- Footer ---- */
.report-footer {
  margin-top: 2.6rem; padding-top: 1.2rem;
  border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem;
}

/* ---- Responsive ---- */
@media (max-width: 720px) {
  .kpi-strip { grid-template-columns: repeat(2, 1fr); }
  .toc ol { columns: 1; }
  .bar-row { grid-template-columns: 110px 1fr 60px; }
}
"""


def render_html(df: pd.DataFrame, period_label: str) -> str:
    n_real = len(df)
    n_users = df["requester.email"].nunique()
    avg_sent = df["sentiment_score"].mean()
    themes = theme_rows(df)
    services = service_rows(df, k=5)
    n_categories = themes["category"].nunique()

    # ---- Section 1: Executive Summary ------------------------------------
    top_theme = themes.iloc[0]
    most_painful = themes.sort_values("avg_sent").iloc[0]
    top_service = services.iloc[0]
    top_categories = (
        themes.groupby("category")["tickets"].sum().sort_values(ascending=False)
    )
    exec_summary = f"""
<section id="executive-summary">
  <h2>1 · Executive Summary</h2>
  <p>Between {df['created_at'].min():%d %B} and {df['created_at'].max():%d %B} 2026,
  AccessRP received <strong>{n_real:,} real customer complaints</strong> from
  <strong>{n_users:,} unique users</strong> (after filtering out automation,
  delivery-failure, and submission-confirmation tickets). Average customer
  sentiment was <strong>{avg_sent:.1f}/100</strong>.</p>

  <p>Tickets clustered into <strong>{n_categories} high-level issue categories</strong>,
  with the largest share belonging to
  <strong>{E(top_categories.index[0])}</strong> ({top_categories.iloc[0]:,} tickets)
  and <strong>{E(top_categories.index[1])}</strong> ({top_categories.iloc[1]:,}).</p>

  <h3>Three findings stakeholders should act on</h3>
  <ol>
    <li><strong>Volume:</strong> <em>{E(top_theme['theme'])}</em> is the
        most-reported issue ({top_theme['tickets']:,} tickets, {top_theme['users']:,} users
        affected). Top services involved: {E(', '.join(top_theme['top_services']))}.</li>
    <li><strong>Severity:</strong> <em>{E(most_painful['theme'])}</em> drives
        the angriest tickets in the period (avg sentiment
        {most_painful['avg_sent']:.0f}). It is concentrated in
        {E(', '.join(most_painful['top_services']))}.</li>
    <li><strong>Service hotspot:</strong> <em>{E(top_service['service'])}</em>
        accounts for {top_service['tickets']:,} of the {n_real:,} tickets
        ({top_service['tickets']/n_real*100:.0f}% of total) — any improvement
        here has the largest immediate volume impact.</li>
  </ol>
  <p class="muted">Methodology, ticket-ID conventions, and PII handling are
  noted in the footer.</p>
</section>
"""

    # ---- Section 2: Key Pain Points --------------------------------------
    pain_html = ['<section id="key-pain-points"><h2>2 · Key Pain Points</h2>',
                 '<p>Pain points are user-experienced frictions, blockers, '
                 'and gaps surfaced across tickets. Each item below '
                 'is backed by example ticket IDs and verbatim user text '
                 '(with PII redacted) for verification.</p>']
    for _, t in themes.head(8).iterrows():
        rec = RECOMMENDATIONS.get(t["theme"], ("", "", ""))
        quotes = pick_quotes(df[df["themes_list"].apply(
            lambda lst, tt=t["theme"]: tt in (lst or []))], t["theme"], k=2)
        pain_html.append(f"""
<div class="pain">
  <div class="title">{E(t['theme'])}</div>
  <div class="stats">{t['tickets']:,} tickets · {t['users']:,} users · avg sentiment {t['avg_sent']:.0f}
   · category: {E(t['category'])}</div>
  <p>{E(rec[1]) if rec[1] else 'Recurring pattern across multiple services.'}</p>
  <div>{ticket_chips(t['sample_ids'])}</div>
  {quote_block(quotes)}
</div>""")
    pain_html.append('</section>')

    # ---- Section 3: Issue Categories Breakdown --------------------------
    cat_summary = (
        themes.groupby("category")
        .agg(tickets=("tickets", "sum"),
             themes=("theme", lambda s: ", ".join(s)),
             sample_ids=("sample_ids", lambda s: [i for sub in s for i in sub][:5]))
        .sort_values("tickets", ascending=False)
        .reset_index()
    )
    cat_total = cat_summary["tickets"].sum()
    cat_rows = "\n".join([
        f"""<tr>
  <td><strong>{E(r['category'])}</strong></td>
  <td class="num">{r['tickets']:,}</td>
  <td class="num">{r['tickets']/cat_total*100:.1f}%</td>
  <td>{E(r['themes'])}</td>
  <td>{ticket_chips(r['sample_ids'])}</td>
</tr>"""
        for _, r in cat_summary.iterrows()
    ])
    cat_html = f"""
<section id="issue-categories">
  <h2>3 · Issue Categories Breakdown</h2>
  <p>Themes have been grouped into eight high-level categories. Percentages
  are computed against the themed-ticket total (one ticket can match
  multiple themes, so totals exceed the per-ticket count).</p>
  <table>
    <thead>
      <tr><th>Category</th><th>Tickets</th><th>%</th><th>Themes</th>
          <th>Sample Ticket IDs</th></tr>
    </thead>
    <tbody>
      {cat_rows}
    </tbody>
  </table>
</section>
"""

    # ---- Section 4: Repeated Issues & Patterns ---------------------------
    pattern_html = ['<section id="repeated-issues"><h2>4 · Repeated Issues & Patterns</h2>',
                    '<p>Below are the most frequently recurring patterns '
                    'extracted from the dataset, each with example ticket '
                    'IDs and the root cause where it can be inferred.</p>']
    repeated = themes.head(6)
    for _, t in repeated.iterrows():
        pattern_html.append(f"""
<h4>{E(t['theme'])} — {t['tickets']:,} tickets</h4>
<p>{E(RECOMMENDATIONS.get(t['theme'], ('', 'Multiple users reported this pattern across the period.', ''))[1])}</p>
<div class="muted" style="font-size:0.85rem;margin-bottom:0.3rem;">
  Top services: {E(', '.join(t['top_services']) or '—')}
</div>
<div>{ticket_chips(t['sample_ids'])}</div>""")
    pattern_html.append('</section>')

    # ---- Section 5: Top 10 Critical Issues -------------------------------
    # Critical = high volume OR low sentiment OR both. Score = tickets * (100 - sent)
    themes_critical = themes.copy()
    themes_critical["score"] = themes_critical.apply(
        lambda r: r["tickets"] * (100 - (r["avg_sent"] if pd.notna(r["avg_sent"]) else 50)),
        axis=1
    )
    themes_critical = themes_critical.sort_values("score", ascending=False).head(10).reset_index(drop=True)
    crit_html = ['<section id="critical-issues"><h2>5 · Top 10 Critical Issues</h2>',
                 '<p>Ranked by <code>tickets × (100 − avg sentiment)</code> — '
                 'high-volume or low-sentiment items rise to the top. '
                 'A high rank here implies either a wide-blast-radius issue '
                 'or a concentrated source of frustration (often both).</p>']
    for i, t in themes_critical.iterrows():
        why = []
        if t["tickets"] >= 100:
            why.append(f"high volume ({t['tickets']:,} tickets)")
        if pd.notna(t["avg_sent"]) and t["avg_sent"] < 35:
            why.append(f"low sentiment ({t['avg_sent']:.0f}/100)")
        if t["users"] >= 100:
            why.append(f"affects {t['users']:,}+ unique users")
        why_str = "; ".join(why) or "recurring multi-service pattern"
        crit_html.append(f"""
<div class="critical">
  <div class="rank">{i+1}</div>
  <div class="body">
    <div class="title">{E(t['theme'])} <span class="badge medium">{E(t['category'])}</span></div>
    <div class="why"><strong>Why critical:</strong> {why_str}.</div>
    <div class="stats">{t['tickets']:,} tickets · {t['users']:,} users
      · avg sentiment {t['avg_sent']:.0f} · top services:
      {E(', '.join(t['top_services']) or '—')}
    </div>
    <div style="margin-top:0.5rem">{ticket_chips(t['sample_ids'])}</div>
  </div>
</div>""")
    crit_html.append('</section>')

    # ---- Section 6: Top 5 Services Analysis ------------------------------
    svc_html = ['<section id="top-services"><h2>6 · Top 5 Services Analysis</h2>',
                '<p>The five services that received the largest share of '
                'real complaints in the period. For each, the dominant '
                'issue patterns and example ticket IDs are listed.</p>']
    for _, s in services.iterrows():
        themes_list = "".join(
            f'<li><strong>{E(t)}</strong> — {c:,} tickets</li>'
            for t, c in s["top_themes"]
        )
        svc_html.append(f"""
<h3>{E(s['service'])} — {s['tickets']:,} tickets · {s['users']:,} users</h3>
<p>Average sentiment {s['avg_sent']:.0f}/100. Most-reported issue patterns
within this service:</p>
<ul>{themes_list}</ul>
<div>Example tickets: {ticket_chips(s['sample_ids'])}</div>""")
    svc_html.append('</section>')

    # ---- Section 7: Service Distribution ---------------------------------
    svc_dist = df["custom_fields.cf_service"].dropna().value_counts().head(12)
    max_v = int(svc_dist.iloc[0])
    bars = "\n".join(bar_row(svc, int(c), max_v) for svc, c in svc_dist.items())
    dist_html = f"""
<section id="service-distribution">
  <h2>7 · Service Distribution</h2>
  <p>Ticket count by service (top 12). The first three services account for
  a disproportionate share of the workload — they're the targets that yield
  the largest deflection wins.</p>
  {bars}
</section>
"""

    # ---- Section 8: Strategic Recommendations ----------------------------
    rec_html = ['<section id="recommendations"><h2>8 · Strategic Recommendations</h2>',
                '<p>Recommendations are ordered by the priority of the theme '
                'they address. Each links back to the pain point and ticket IDs '
                'in earlier sections.</p>']
    seen_themes = set()
    for _, t in themes_critical.iterrows():
        if t["theme"] in seen_themes:
            continue
        seen_themes.add(t["theme"])
        rec = RECOMMENDATIONS.get(t["theme"])
        if not rec:
            continue
        title, body, priority = rec
        klass = priority.lower().replace("/", "")
        rec_html.append(f"""
<div class="rec">
  <div class="head"><span class="badge {klass}">{E(priority)} priority</span>
    <span class="title">{E(title)}</span></div>
  <div class="why">{E(body)}</div>
  <div class="muted" style="font-size:0.85rem;">Addresses:
    <em>{E(t['theme'])}</em> · {t['tickets']:,} tickets · {t['users']:,} users
    · sample: {ticket_chips(t['sample_ids'][:3])}
  </div>
</div>""")
    rec_html.append('</section>')

    # ---- KPI strip + header + TOC ----------------------------------------
    kpis = f"""
<div class="kpi-strip">
  <div class="kpi"><div class="label">Real complaints reviewed</div>
    <div class="value">{n_real:,}</div>
    <div class="sub">noise & automation filtered out</div></div>
  <div class="kpi"><div class="label">Unique users affected</div>
    <div class="value">{n_users:,}</div>
    <div class="sub">distinct requester emails</div></div>
  <div class="kpi"><div class="label">Distinct issue themes</div>
    <div class="value">{len(themes)}</div>
    <div class="sub">grouped into {n_categories} categories</div></div>
  <div class="kpi"><div class="label">Avg sentiment (0–100)</div>
    <div class="value">{avg_sent:.1f}</div>
    <div class="sub">Freshdesk score, higher = happier</div></div>
</div>
"""

    toc = """
<nav class="toc">
  <h3>Contents</h3>
  <ol>
    <li><a href="#executive-summary">Executive Summary</a></li>
    <li><a href="#key-pain-points">Key Pain Points</a></li>
    <li><a href="#issue-categories">Issue Categories Breakdown</a></li>
    <li><a href="#repeated-issues">Repeated Issues &amp; Patterns</a></li>
    <li><a href="#critical-issues">Top 10 Critical Issues</a></li>
    <li><a href="#top-services">Top 5 Services Analysis</a></li>
    <li><a href="#service-distribution">Service Distribution</a></li>
    <li><a href="#recommendations">Strategic Recommendations</a></li>
  </ol>
</nav>
"""

    footer = f"""
<div class="report-footer">
  <p><strong>Methodology.</strong> Source data: AccessRP Freshdesk export
  for the period covered. Tickets in the
  &ldquo;Ads Test Tickets and Auto-Emails&rdquo; service and tickets matching
  auto-reply / delivery-failure / submission-confirmation patterns are
  excluded from this analysis. Themes are derived via a rule-based classifier
  applied to subject and description text.</p>

  <p><strong>Ticket IDs.</strong> Numeric IDs are Freshdesk's internal
  ticket numbers and are meaningless without access to the helpdesk.</p>

  <p><strong>PII handling.</strong> Verbatim quotes have been redacted:
  email addresses, phone numbers, EID-style identifiers, application
  reference numbers, unit numbers, licence numbers, passport numbers, and
  URLs are replaced with bracketed placeholders. Customer names that appear
  inside the prose body are <em>not</em> automatically masked &mdash; review
  before publishing if your dataset contains names embedded in
  free-text descriptions.</p>

  <p class="muted" style="margin-top:1.2rem;">
    Generated on {pd.Timestamp.now():%Y-%m-%d %H:%M} ·
    Source repo:
    <a href="https://github.com/ymedhatadres/accessrp-dashboard"
       style="color: var(--navy);">ymedhatadres/accessrp-dashboard</a>
  </p>
</div>
"""

    title_html = f"""
<header class="report-header">
  <h1>AccessRP &mdash; User Feedback Insights</h1>
  <div class="meta">{E(period_label)} · ADGM real-estate services portal
  · {n_real:,} complaints reviewed</div>
</header>
"""

    body = "\n".join([
        title_html, kpis, toc,
        exec_summary,
        "\n".join(pain_html),
        cat_html,
        "\n".join(pattern_html),
        "\n".join(crit_html),
        "\n".join(svc_html),
        dist_html,
        "\n".join(rec_html),
        footer,
    ])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AccessRP — User Feedback Insights ({E(period_label)})</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="wrap">
    {body}
  </div>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter", help="e.g. '2026 Q1', '2026 Q2'")
    parser.add_argument("--all", action="store_true", help="use the full dataset")
    args = parser.parse_args()

    df, period = load_period(args.quarter, args.all)
    print(f"Building report for: {period}  ({len(df):,} real complaints)")

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html_str = render_html(df, period)
    OUT_HTML.write_text(html_str)
    print(f"Wrote {OUT_HTML}  ({OUT_HTML.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
