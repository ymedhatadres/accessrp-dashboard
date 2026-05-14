"""Root-cause / issue-source drill-down tab."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..data import (
    AREA_COL,
    ISSUE_SOURCE_COL,
    PLATFORM_COL,
    ROOT_CAUSE_COL,
    SERVICE_COL,
)


def _top_bar(df: pd.DataFrame, col: str, title: str, n: int = 15) -> None:
    st.markdown(f"### {title}")
    s = df[col].value_counts(dropna=True).head(n).reset_index()
    if s.empty:
        st.caption("No tagged tickets in current filter.")
        return
    s.columns = [title, "tickets"]
    fig = px.bar(s, x="tickets", y=title, orientation="h")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)


def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    tagged = df[df[ROOT_CAUSE_COL].notna()]
    total, n_tagged = len(df), len(tagged)
    pct = (n_tagged / total * 100) if total else 0
    st.caption(
        f"Only **{n_tagged:,} of {total:,}** tickets ({pct:.1f}%) have a root-cause "
        "tagged by the support team — root-cause analysis is restricted to these."
    )

    if tagged.empty:
        st.info("No tagged tickets in current filter.")
        return

    c1, c2 = st.columns(2)
    with c1:
        _top_bar(tagged, ROOT_CAUSE_COL, "Root cause")
        _top_bar(tagged, AREA_COL, "Area of impact")
    with c2:
        _top_bar(tagged, ISSUE_SOURCE_COL, "Issue source")
        _top_bar(tagged, PLATFORM_COL, "Platform")

    st.markdown("### Root cause × service")
    cross = (
        tagged.groupby([ROOT_CAUSE_COL, SERVICE_COL], dropna=True)
        .size()
        .reset_index(name="tickets")
    )
    top_causes = (
        tagged[ROOT_CAUSE_COL].value_counts().head(8).index.tolist()
    )
    cross = cross[cross[ROOT_CAUSE_COL].isin(top_causes)]
    if not cross.empty:
        fig = px.bar(cross, x="tickets", y=ROOT_CAUSE_COL, color=SERVICE_COL,
                     orientation="h")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                          yaxis={"categoryorder": "total ascending"},
                          legend_title="Service")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Top 20 root-cause + service combinations")
    combo = (
        tagged.groupby([ROOT_CAUSE_COL, SERVICE_COL], dropna=True)
        .agg(tickets=("id", "size"), avg_sentiment=("sentiment_score", "mean"))
        .reset_index()
        .sort_values("tickets", ascending=False)
        .head(20)
    )
    combo["avg_sentiment"] = combo["avg_sentiment"].round(1)
    combo = combo.rename(columns={
        ROOT_CAUSE_COL: "root_cause",
        SERVICE_COL: "service",
    })
    st.dataframe(combo, use_container_width=True, hide_index=True)
