"""Sentiment & customer experience tab."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..data import ROOT_CAUSE_COL, SERVICE_COL
from ..theme import SENTIMENT_BUCKET_COLORS


def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    with_score = df[df["sentiment_score"].notna()]
    if with_score.empty:
        st.info("No tickets have a sentiment score in the current filter.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Avg sentiment", f"{with_score['sentiment_score'].mean():.1f}",
              help="Freshdesk score 0–100; higher = more positive")
    c2.metric("Median sentiment", f"{with_score['sentiment_score'].median():.1f}")
    neg = (with_score["sentiment_bucket"] == "Negative").sum()
    c3.metric("Negative tickets", f"{neg:,}",
              delta=f"{neg / len(with_score) * 100:.1f}%", delta_color="inverse")

    st.markdown("### Sentiment score distribution")
    fig = px.histogram(with_score, x="sentiment_score", nbins=40,
                       color="sentiment_bucket",
                       color_discrete_map=SENTIMENT_BUCKET_COLORS)
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                      bargap=0.05, legend_title="Bucket")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Sentiment bucket by service")
    by_svc = (
        with_score.groupby([SERVICE_COL, "sentiment_bucket"], dropna=True,
                           observed=True)
        .size()
        .reset_index(name="tickets")
    )
    top_services = (
        with_score[SERVICE_COL].value_counts().head(10).index.tolist()
    )
    by_svc = by_svc[by_svc[SERVICE_COL].isin(top_services)]
    if not by_svc.empty:
        fig_s = px.bar(by_svc, x=SERVICE_COL, y="tickets", color="sentiment_bucket",
                       color_discrete_map=SENTIMENT_BUCKET_COLORS)
        fig_s.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                            xaxis_title="Service", legend_title="Bucket")
        st.plotly_chart(fig_s, use_container_width=True)

    st.markdown("### Sentiment bucket by root cause (tagged tickets only)")
    tagged = with_score[with_score[ROOT_CAUSE_COL].notna()]
    if not tagged.empty:
        by_rc = (
            tagged.groupby([ROOT_CAUSE_COL, "sentiment_bucket"], dropna=True,
                           observed=True)
            .size()
            .reset_index(name="tickets")
        )
        top_rc = tagged[ROOT_CAUSE_COL].value_counts().head(8).index.tolist()
        by_rc = by_rc[by_rc[ROOT_CAUSE_COL].isin(top_rc)]
        fig_rc = px.bar(by_rc, x=ROOT_CAUSE_COL, y="tickets",
                        color="sentiment_bucket",
                        color_discrete_map={"Negative": "#d62728",
                                            "Neutral": "#7f7f7f",
                                            "Positive": "#2ca02c"})
        fig_rc.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                             xaxis_title="Root cause", legend_title="Bucket")
        st.plotly_chart(fig_rc, use_container_width=True)
    else:
        st.caption("No tagged tickets in current filter.")

    st.markdown("### 20 most-negative tickets")
    cols = ["id", "subject", SERVICE_COL, ROOT_CAUSE_COL, "sentiment_score",
            "status_label", "created_at"]
    cols = [c for c in cols if c in with_score.columns]
    worst = (
        with_score.sort_values("sentiment_score", ascending=True)
        .head(20)[cols]
        .rename(columns={SERVICE_COL: "service", ROOT_CAUSE_COL: "root_cause"})
    )
    st.dataframe(worst, use_container_width=True, hide_index=True)

    st.markdown("### Repeat requesters (≥3 tickets) — lowest avg sentiment")
    if "requester.email" in df.columns:
        rep = (
            df.groupby("requester.email", dropna=True)
            .agg(tickets=("id", "size"),
                 avg_sentiment=("sentiment_score", "mean"),
                 top_service=(SERVICE_COL,
                              lambda s: s.value_counts().idxmax() if s.notna().any() else None))
            .reset_index()
        )
        rep = rep[rep["tickets"] >= 3].sort_values("avg_sentiment", ascending=True)
        rep["avg_sentiment"] = rep["avg_sentiment"].round(1)
        st.dataframe(rep.head(30), use_container_width=True, hide_index=True)
