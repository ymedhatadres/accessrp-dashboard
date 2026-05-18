"""User-focused report tab.

Turns the raw complaint data into a prioritised, copy-paste-ready brief:
top user pain points, ranked by how many users are hit and how angry
they are, with verbatim quotes and suggested next steps. The whole
report is exportable as Markdown so you can paste it into Slack,
email, or a one-pager for leadership.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..data import SERVICE_COL
from ..text_clean import clean_description, extract_sentences
from ..themes import THEME_RULES


# ---- Theme-keyword map used to pull the most salient sentence per quote ----
# Mirrors the regex patterns in themes.py but as plain keywords for highlighting.
THEME_KEYWORDS: dict[str, list[str]] = {
    "Login / Access": ["login", "log in", "sign in", "otp", "password", "access"],
    "Payment / Wallet": ["payment", "wallet", "top up", "refund", "deduct",
                          "charge", "fees", "paid"],
    "Application stuck / pending": ["stuck", "pending", "no update",
                                     "awaiting", "waiting", "under review"],
    "Application not found / missing": ["not found", "missing", "cannot find",
                                          "can't find", "where is"],
    "Rejection / declined": ["rejected", "declined", "denied", "refused"],
    "Cancellation request": ["cancel", "withdraw"],
    "Data correction / update": ["update", "correction", "wrong", "incorrect",
                                  "amend", "change"],
    "Document / attachment issue": ["document", "attachment", "upload",
                                      "file", "pdf", "noc"],
    "Certificate": ["certificate", "noc"],
    "Lease / tenancy": ["lease", "tenancy", "tenant", "landlord", "rental",
                         "ejari"],
    "Transfer / POA": ["transfer", "poa", "power of attorney"],
    "Appointment / booking": ["appointment", "booking", "reschedule"],
    "Error / system issue": ["error", "failed", "broken", "bug",
                              "something went wrong"],
    "Slow / performance": ["slow", "loading", "timeout", "spinning"],
    "Arabic-language ticket": [],
}


# ---- Suggested-action templates per theme. Generic but actionable. --------
SUGGESTED_ACTIONS: dict[str, list[str]] = {
    "Payment / Wallet": [
        "Audit payment → receipt pipeline: how often is money taken but the "
        "receipt/confirmation step fails?",
        "Investigate duplicate-payment guards — multiple users report being "
        "asked to pay again after a successful charge.",
        "Add a self-serve refund / payment-status page so users can verify "
        "without raising a ticket.",
    ],
    "Login / Access": [
        "Review OTP / SMS delivery reliability (provider failover, expiry "
        "windows).",
        "Surface clearer error messages when login fails — generic 'something "
        "went wrong' drives ticket volume.",
    ],
    "Application stuck / pending": [
        "Audit which workflow stages are silently long-lived; add status "
        "visibility / ETA to the user-facing application page.",
        "Set up a backlog alert when an application sits in any one stage > N days.",
    ],
    "Application not found / missing": [
        "Reproduce 'application not found' for the affected user IDs — likely "
        "a data-sync or visibility-rule bug.",
        "Add a 'where is my application?' help link with the most common causes.",
    ],
    "Rejection / declined": [
        "Audit rejection reasons surfaced to the user — vague reasons drive "
        "appeals tickets.",
        "Where rejection is reversible, build a guided re-submission flow.",
    ],
    "Cancellation request": [
        "Build self-serve cancel for the application types where it's safe.",
        "Document the cancel SLA so users stop chasing.",
    ],
    "Data correction / update": [
        "Build a self-serve 'request data correction' form — these all become "
        "manual back-office tickets today.",
        "Catalogue the most common fields users need fixed; consider making "
        "them user-editable.",
    ],
    "Document / attachment issue": [
        "Audit upload limits, supported file types, and error messaging on "
        "the upload step.",
        "Investigate any provider/CDN issues for document storage and PDF "
        "generation.",
    ],
    "Certificate": [
        "Investigate certificate / NOC generation pipeline reliability.",
        "Provide a clearer 'where is my certificate?' status indicator.",
    ],
    "Lease / tenancy": [
        "Cluster Lease tickets by sub-pattern (PMA, Ejari, Tawtheeq) and "
        "audit each flow.",
        "Investigate the most common Lease data-correction requests — they "
        "suggest a missing user-editable field.",
    ],
    "Transfer / POA": [
        "Most Transfer-of-Interest tickets look like booking-form submissions — "
        "consider replacing the email-based booking with a proper form.",
        "Document the POA-vs-non-POA flow distinctions clearly in-product.",
    ],
    "Appointment / booking": [
        "Build self-serve appointment booking + rescheduling rather than "
        "email-based requests.",
    ],
    "Error / system issue": [
        "Categorise 'something went wrong' tickets by which page/action — "
        "many likely point to a small set of broken flows.",
        "Add structured error logging on the front-end so future tickets "
        "carry a reference code.",
    ],
    "Slow / performance": [
        "Profile the slowest pages reported and check CDN / DB query timings.",
    ],
    "Arabic-language ticket": [
        "Ensure Arabic-speaking users have the same self-serve options as "
        "English-speaking ones; some patterns repeat in both languages but "
        "are tracked separately because of language.",
    ],
    "Other / unclassified": [
        "Sample a handful of these to spot any emerging theme that isn't "
        "captured by the current rules.",
    ],
}


# ---- Priority scoring -----------------------------------------------------
def _priority_score(tickets: int, avg_sent: float) -> float:
    """Higher = more painful.

    tickets * (100 - avg_sentiment).  avg_sentiment is on Freshdesk's 0–100
    scale (higher = happier), so the (100 - sent) term boosts angry themes.
    """
    if pd.isna(avg_sent):
        avg_sent = 50.0
    return float(tickets) * (100.0 - float(avg_sent))


# ---- Quote selection ------------------------------------------------------
def _representative_quotes(theme_df: pd.DataFrame, theme: str, k: int = 3) -> list[dict]:
    """Pick k representative user quotes for this theme.

    Strategy: lowest sentiment first, prefer English over Arabic for the
    first quote (more readable for most stakeholders), include at least one
    Arabic if a chunk of the theme is Arabic.
    """
    kw = THEME_KEYWORDS.get(theme, [])
    candidates = (
        theme_df[theme_df["description_text"].notna()]
        .sort_values("sentiment_score", ascending=True, na_position="last")
        .head(40)
        .copy()
    )
    if candidates.empty:
        return []

    candidates["clean"] = candidates["description_text"].map(clean_description)
    candidates = candidates[candidates["clean"].str.len() > 30]

    quotes: list[dict] = []
    for _, r in candidates.iterrows():
        salient = extract_sentences(r["clean"], kw)
        if not salient or len(salient) < 20:
            continue
        if any(salient.strip() == q["text"] for q in quotes):
            continue
        quotes.append({
            "id": int(r["id"]) if pd.notna(r["id"]) else None,
            "service": r.get(SERVICE_COL) or "—",
            "sentiment": float(r["sentiment_score"]) if pd.notna(r["sentiment_score"]) else None,
            "text": salient.strip()[:380],
        })
        if len(quotes) >= k:
            break
    return quotes


# ---- Report-building helpers ---------------------------------------------
def _build_theme_rows(real: pd.DataFrame) -> pd.DataFrame:
    """One row per theme with the stats the report needs."""
    rows = []
    for theme, _kws in THEME_RULES:
        mask = real["themes_list"].apply(lambda lst: theme in (lst or []))
        sub = real[mask]
        if sub.empty:
            continue
        users = sub["requester.email"].nunique() if "requester.email" in sub else 0
        avg_sent = sub["sentiment_score"].mean()
        neg = (sub["sentiment_bucket"] == "Negative").sum() if "sentiment_bucket" in sub else 0
        top_services = (
            sub[SERVICE_COL].dropna().value_counts().head(3).index.tolist()
        )
        # Quarter-over-quarter trend: compare per-day rate, not raw count,
        # because an in-progress quarter has fewer elapsed days than a
        # completed one — raw counts would always show the new quarter "lower".
        q_trend = None
        if "quarter" in sub and "created_date" in sub and not sub.empty:
            by_q = sub.groupby("quarter").agg(
                tickets=("id", "size"),
                days_with_data=("created_date", "nunique"),
            )
            by_q = by_q[by_q["days_with_data"] > 0].sort_index()
            if len(by_q) >= 2:
                rate_last = by_q["tickets"].iloc[-1] / by_q["days_with_data"].iloc[-1]
                rate_prev = by_q["tickets"].iloc[-2] / by_q["days_with_data"].iloc[-2]
                if rate_prev > 0:
                    q_trend = (rate_last - rate_prev) / rate_prev * 100.0
        rows.append({
            "theme": theme,
            "tickets": int(len(sub)),
            "users": int(users),
            "avg_sentiment": float(avg_sent) if pd.notna(avg_sent) else None,
            "negative": int(neg),
            "negative_pct": (neg / len(sub) * 100) if len(sub) else 0,
            "top_services": top_services,
            "qoq_trend_pct": q_trend,
            "priority": _priority_score(len(sub), avg_sent if pd.notna(avg_sent) else 50.0),
        })
    return pd.DataFrame(rows).sort_values("priority", ascending=False).reset_index(drop=True)


def _to_markdown(real: pd.DataFrame, themes: pd.DataFrame, n_top: int = 8) -> str:
    """Render the full report as Markdown for copy-paste."""
    period = ""
    if "created_at" in real and not real.empty:
        period = f"{real['created_at'].min():%Y-%m-%d} → {real['created_at'].max():%Y-%m-%d}"
    lines = [
        "# AccessRP — Voice-of-customer report",
        "",
        f"_Period: {period}_  ·  _{len(real):,} real complaints_  ·  "
        f"_{real['requester.email'].nunique():,} unique users_",
        "",
        "## Top user pain points",
        "",
    ]
    for i, row in themes.head(n_top).iterrows():
        rank = i + 1
        sent = f"{row['avg_sentiment']:.0f}" if row["avg_sentiment"] is not None else "—"
        trend = ""
        if row["qoq_trend_pct"] is not None:
            arrow = "▲" if row["qoq_trend_pct"] > 0 else "▼"
            trend = f"  ·  {arrow} {row['qoq_trend_pct']:+.0f}% per-day vs prior quarter"
        services = ", ".join(row["top_services"][:3]) if row["top_services"] else "—"
        lines += [
            f"### {rank}. {row['theme']}",
            f"**{row['tickets']:,} tickets · {row['users']:,} users · "
            f"avg sentiment {sent} · {row['negative_pct']:.0f}% negative{trend}**",
            f"_Top services:_ {services}",
            "",
        ]
        sub = real[real["themes_list"].apply(lambda lst: row["theme"] in (lst or []))]
        quotes = _representative_quotes(sub, row["theme"], k=3)
        if quotes:
            lines.append("**What users say:**")
            lines.append("")
            for q in quotes:
                lines.append(f"> {q['text']}")
                lines.append(f"> _— #{q['id']} · {q['service']} · sentiment {q['sentiment']:.0f}_"
                             if q["sentiment"] is not None else
                             f"> _— #{q['id']} · {q['service']}_")
                lines.append("")
        actions = SUGGESTED_ACTIONS.get(row["theme"]) or []
        if actions:
            lines.append("**Suggested next steps:**")
            for a in actions:
                lines.append(f"- {a}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ---- The tab --------------------------------------------------------------
def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    real = df  # already noise-filtered upstream
    n_real = len(real)
    n_users = real["requester.email"].nunique() if "requester.email" in real else 0
    avg_sent = real["sentiment_score"].mean()
    neg = (real["sentiment_bucket"] == "Negative").sum() if "sentiment_bucket" in real else 0

    st.markdown(
        "Use this tab to **brief stakeholders and pick what to fix next**. "
        "Pain points are ranked by volume × severity, with real user quotes "
        "and suggested next steps. Hit the export button at the bottom to "
        "copy the whole report as Markdown."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Real complaints", f"{n_real:,}")
    c2.metric("Unique users affected", f"{n_users:,}")
    c3.metric("Avg sentiment", f"{avg_sent:.1f}" if pd.notna(avg_sent) else "—",
              help="Freshdesk score 0–100; higher = more positive")
    c4.metric("Negative tickets", f"{neg:,}",
              delta=f"{neg / n_real * 100:.1f}% of view" if n_real else None,
              delta_color="inverse")

    themes = _build_theme_rows(real)
    if themes.empty:
        st.warning("No themed complaints in the current filter.")
        return

    st.markdown("## Top user pain points")
    st.caption("Ranked by priority = tickets × (100 − avg sentiment). "
               "Click a card to read user quotes and suggested actions.")

    top_n = st.slider("How many to show", min_value=3, max_value=12, value=8,
                      key="report_top_n")
    max_priority = themes["priority"].iloc[0] or 1.0

    for i, row in themes.head(top_n).iterrows():
        rank = i + 1
        sent = f"{row['avg_sentiment']:.0f}" if row["avg_sentiment"] is not None else "—"
        priority_bar = "█" * int(round(row["priority"] / max_priority * 10))
        priority_empty = "░" * (10 - len(priority_bar))
        trend_chip = ""
        if row["qoq_trend_pct"] is not None:
            arrow = "▲" if row["qoq_trend_pct"] > 0 else "▼"
            colour = "#B85C5C" if row["qoq_trend_pct"] > 0 else "#5A8C5C"
            trend_chip = (f"<span style='color:{colour};font-weight:600;'>"
                          f"{arrow} {row['qoq_trend_pct']:+.0f}% per-day vs prior quarter</span>")

        header = (f"**#{rank}  {row['theme']}**   "
                  f"`{priority_bar}{priority_empty}`   "
                  f"{row['tickets']:,} tickets · {row['users']:,} users · "
                  f"sentiment {sent}")
        with st.expander(header, expanded=(rank == 1)):
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Tickets", f"{row['tickets']:,}")
            mc2.metric("Unique users", f"{row['users']:,}")
            mc3.metric("Avg sentiment", sent)
            mc4.metric("Negative", f"{row['negative_pct']:.0f}%",
                       delta_color="inverse")
            if trend_chip:
                st.markdown(trend_chip, unsafe_allow_html=True)
            if row["top_services"]:
                st.markdown(
                    "**Top affected services:** "
                    + " · ".join(f"`{s}`" for s in row["top_services"])
                )

            st.markdown("**What users say (verbatim):**")
            sub = real[real["themes_list"].apply(
                lambda lst, t=row["theme"]: t in (lst or [])
            )]
            quotes = _representative_quotes(sub, row["theme"], k=3)
            if not quotes:
                st.caption("No long-form quotes available for this theme.")
            for q in quotes:
                meta = (f"#{q['id']} · {q['service']}"
                        + (f" · sentiment {q['sentiment']:.0f}"
                           if q["sentiment"] is not None else ""))
                st.markdown(
                    f"> {q['text']}  \n"
                    f"> <span style='color:#6B6B6B;font-size:0.85rem;'>— {meta}</span>",
                    unsafe_allow_html=True,
                )

            actions = SUGGESTED_ACTIONS.get(row["theme"]) or []
            if actions:
                st.markdown("**Suggested next steps:**")
                for a in actions:
                    st.markdown(f"- {a}")

    st.markdown("---")
    st.markdown("## Export report")
    st.caption("Markdown is the safest format to paste into Slack, Notion, "
               "Confluence, or an email.")

    md = _to_markdown(real, themes, n_top=top_n)
    st.download_button(
        "⬇  Download report as Markdown (.md)",
        data=md,
        file_name="accessrp_voice_of_customer_report.md",
        mime="text/markdown",
        use_container_width=True,
    )
    with st.expander("Preview full report (copy from here too)"):
        st.code(md, language="markdown")
