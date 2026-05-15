"""Voice-of-customer tab: what users actually complain about, with examples."""

from __future__ import annotations

import re

import pandas as pd
import plotly.express as px
import streamlit as st

from ..data import SERVICE_COL
from ..theme import DIVERGING_SENTIMENT
from ..themes import classify, theme_summary, top_ngrams


@st.cache_data(show_spinner=False)
def _classify_cached(df: pd.DataFrame) -> pd.DataFrame:
    return classify(df)


def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    classified = _classify_cached(df)
    n_real = len(classified)
    themed = int((classified["theme_primary"] != "Other / unclassified").sum())
    avg_s = classified["sentiment_score"].mean()
    neg_pct = (
        (classified["sentiment_bucket"] == "Negative").mean() * 100
        if "sentiment_bucket" in classified else 0
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Real complaints", f"{n_real:,}")
    c2.metric("Themed complaints", f"{themed:,}",
              delta=f"{themed / n_real * 100:.1f}% of real" if n_real else None,
              help="Tickets that matched at least one known theme.")
    c3.metric("Avg sentiment", f"{avg_s:.1f}" if pd.notna(avg_s) else "—",
              help="Freshdesk score 0–100; higher = more positive")
    c4.metric("Negative tickets", f"{neg_pct:.1f}%",
              help="Share of real complaints with sentiment_score < 20.",
              delta_color="inverse")

    real = classified
    if real.empty:
        st.warning("No real complaints in the current filter.")
        return

    st.markdown("## Themes — what users complain about")
    summary = theme_summary(classified)
    summary["share %"] = (summary["tickets"] / n_real * 100).round(1)
    summary = summary.rename(columns={
        "tickets": "tickets matched",
        "avg_sentiment": "avg sentiment",
        "top_service": "top service",
    })[["theme", "tickets matched", "share %", "top service", "avg sentiment"]]

    fig = px.bar(summary.sort_values("tickets matched"),
                 x="tickets matched", y="theme", orientation="h",
                 color="avg sentiment", color_continuous_scale=DIVERGING_SENTIMENT,
                 range_color=[0, 100], hover_data=["top service", "share %"])
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10),
                      coloraxis_colorbar=dict(title="Avg sent."))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Theme summary table")
    st.dataframe(summary, use_container_width=True, hide_index=True)
    st.caption("A ticket can match multiple themes, so totals can exceed the "
               "real-complaint count.")

    st.markdown("## Theme deep-dive — counts, services, and example tickets")
    themes_sorted = summary["theme"].tolist()
    selected = st.selectbox("Pick a theme to inspect", themes_sorted, index=0)
    theme_mask = real["themes_list"].apply(lambda lst: selected in (lst or []))
    theme_df = real[theme_mask]

    if theme_df.empty:
        st.info("No tickets match this theme in the current filter.")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("Tickets", f"{len(theme_df):,}")
        m2.metric("Avg sentiment", f"{theme_df['sentiment_score'].mean():.1f}")
        neg = int((theme_df["sentiment_bucket"] == "Negative").sum())
        m3.metric("Negative sentiment", f"{neg:,}",
                  delta=f"{neg / len(theme_df) * 100:.1f}%",
                  delta_color="inverse")

        st.markdown("**Top services for this theme**")
        svc = theme_df[SERVICE_COL].value_counts(dropna=True).head(8).reset_index()
        svc.columns = ["service", "tickets"]
        st.dataframe(svc, use_container_width=True, hide_index=True)

        st.markdown("**10 example tickets (lowest sentiment first)**")
        cols = ["id", "subject", SERVICE_COL, "sentiment_score", "status_label",
                "created_at", "description_text"]
        cols = [c for c in cols if c in theme_df.columns]
        examples = (
            theme_df.sort_values("sentiment_score", ascending=True, na_position="last")
            .head(10)[cols]
            .rename(columns={SERVICE_COL: "service",
                             "description_text": "description (truncated)"})
        )
        st.dataframe(examples, use_container_width=True, hide_index=True)

    st.markdown("## Most common phrases in real complaints")
    cc1, cc2 = st.columns(2)
    subjects = real["subject"].dropna().tolist()
    descs = real["description_text"].dropna().tolist()
    with cc1:
        st.markdown("**Top bigrams in subjects**")
        st.dataframe(top_ngrams(subjects, n=2, k=20),
                     use_container_width=True, hide_index=True)
    with cc2:
        st.markdown("**Top trigrams in subjects**")
        st.dataframe(top_ngrams(subjects, n=3, k=20),
                     use_container_width=True, hide_index=True)
    with st.expander("Top bigrams in descriptions (slower)"):
        st.dataframe(top_ngrams(descs, n=2, k=30),
                     use_container_width=True, hide_index=True)

    st.markdown("## Search ticket text")
    query = st.text_input("Search subject + description (case-insensitive)",
                          value="", placeholder="e.g. refund, transfer of interest")
    if query.strip():
        q = re.escape(query.strip())
        hay = (real["subject"].astype("string").fillna("") + " " +
               real["description_text"].astype("string").fillna(""))
        hits = real[hay.str.contains(q, case=False, na=False, regex=True)]
        st.caption(f"{len(hits):,} matching tickets")
        cols = ["id", "subject", SERVICE_COL, "theme_primary", "sentiment_score",
                "status_label", "created_at", "description_text"]
        cols = [c for c in cols if c in hits.columns]
        st.dataframe(
            hits.sort_values("created_at", ascending=False).head(200)[cols]
            .rename(columns={SERVICE_COL: "service",
                             "description_text": "description (truncated)"}),
            use_container_width=True, hide_index=True,
        )
