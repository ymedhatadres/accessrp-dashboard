"""Qualitative reading view: actual cleaned ticket descriptions by theme."""

from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from ..data import SERVICE_COL
from ..text_clean import add_clean_columns, extract_sentences
from ..themes import THEME_RULES, classify

# Map theme name -> keyword list used to pull the most-salient sentence.
_THEME_KEYWORDS = {
    "Login / Access": ["login", "log in", "sign in", "otp", "password", "access"],
    "Payment / Wallet": ["payment", "wallet", "top up", "top-up", "refund",
                          "deduct", "charge", "fees", "fee"],
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


@st.cache_data(show_spinner="Cleaning descriptions...")
def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    cls = classify(df)
    enriched = add_clean_columns(cls)
    return enriched


def _highlight(text: str, keywords: list[str]) -> str:
    if not text or not keywords:
        return text
    pattern = "|".join(re.escape(k) for k in keywords)
    return re.sub(f"(?i)({pattern})", r"**\1**", text)


def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    prepared = _prepare(df)
    real = prepared[
        (~prepared["is_noise"])
        & (~prepared["is_form_template"])
        & (prepared["description_clean"].str.len() > 20)
    ]

    n_total = len(prepared)
    n_real = int((~prepared["is_noise"]).sum())
    n_forms = int(prepared["is_form_template"].sum())
    n_readable = len(real)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tickets in view", f"{n_total:,}")
    c2.metric("Real complaints", f"{n_real:,}")
    c3.metric("Form-template submissions", f"{n_forms:,}",
              help="Structured booking-request emails — excluded from qualitative view.")
    c4.metric("Readable descriptions", f"{n_readable:,}",
              help="Real complaints with a non-empty description after cleaning.")

    st.caption(
        "This tab strips email banners, greetings, signatures, and disclaimers "
        "from each description so you can read the actual complaint body. "
        "Form-template submissions (e.g. 'Appointment Type: Transfer of Interest') "
        "are filtered out separately — they are structured forms, not free-text complaints."
    )

    if real.empty:
        st.warning("No readable real complaints in the current filter.")
        return

    st.markdown("## Reading list by theme")

    available_themes = [name for name, _ in THEME_RULES]
    available_themes = [
        t for t in available_themes
        if real["themes_list"].apply(lambda lst: t in (lst or [])).any()
    ]
    if not available_themes:
        st.info("No themed complaints in this filter.")
        return

    colA, colB, colC = st.columns([2, 2, 1])
    with colA:
        theme = st.selectbox("Theme", available_themes, index=0,
                             key="qual_theme")
    with colB:
        services = sorted(
            real[SERVICE_COL].dropna().astype(str).unique().tolist()
        )
        svc_pick = st.multiselect("Service (optional)", services,
                                   key="qual_svc")
    with colC:
        sort_by = st.selectbox(
            "Sort", ["Lowest sentiment", "Most recent", "Longest description"],
            index=0, key="qual_sort",
        )

    mask = real["themes_list"].apply(lambda lst: theme in (lst or []))
    subset = real[mask]
    if svc_pick:
        subset = subset[subset[SERVICE_COL].astype(str).isin(svc_pick)]

    if subset.empty:
        st.info("No tickets match this theme/service combination.")
        return

    if sort_by == "Lowest sentiment":
        subset = subset.sort_values("sentiment_score", ascending=True,
                                     na_position="last")
    elif sort_by == "Most recent":
        subset = subset.sort_values("created_at", ascending=False)
    else:
        subset = subset.assign(_len=subset["description_clean"].str.len())
        subset = subset.sort_values("_len", ascending=False)

    keywords = _THEME_KEYWORDS.get(theme, [])

    st.markdown(f"### Salient sentences (top 30 of {len(subset):,} tickets)")
    rows = []
    for _, r in subset.head(30).iterrows():
        salient = extract_sentences(r["description_clean"], keywords)
        rows.append({
            "id": r["id"],
            "service": r[SERVICE_COL],
            "sentiment": r["sentiment_score"],
            "salient sentence(s)": salient[:400],
            "subject": r["subject"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown(f"### Read 10 full complaints — '{theme}'")
    show_n = min(10, len(subset))
    for _, r in subset.head(show_n).iterrows():
        title = f"#{r['id']} · {r[SERVICE_COL] or '—'} · sentiment {r['sentiment_score']:.0f}" \
            if pd.notna(r["sentiment_score"]) else f"#{r['id']} · {r[SERVICE_COL] or '—'}"
        with st.expander(f"{title} — {str(r['subject'])[:90]}"):
            st.caption(
                f"Created {r['created_at']:%Y-%m-%d %H:%M} · "
                f"Status: {r['status_label']} · "
                f"Themes: {', '.join(r['themes_list'])}"
            )
            highlighted = _highlight(r["description_clean"], keywords)
            st.markdown(highlighted if highlighted else "_(empty after cleaning)_")

    st.markdown("---")
    st.markdown("## Search verbatim text (real complaints only)")
    query = st.text_input(
        "Search cleaned description text",
        value="", placeholder="e.g. payment deducted, OTP not received, refund",
        key="qual_search",
    )
    if query.strip():
        q_re = re.escape(query.strip())
        hits = real[real["description_clean"].str.contains(
            q_re, case=False, na=False, regex=True
        )]
        st.caption(f"{len(hits):,} matching descriptions")
        for _, r in hits.head(15).iterrows():
            with st.expander(
                f"#{r['id']} · {r[SERVICE_COL] or '—'} · {r['theme_primary']} — "
                f"{str(r['subject'])[:80]}"
            ):
                st.markdown(_highlight(r["description_clean"], [query.strip()]))
