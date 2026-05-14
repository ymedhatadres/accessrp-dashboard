"""Leadership KPI tab."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..data import SERVICE_COL
from ..themes import NOISE_SERVICE


def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    total = len(df)
    resolved = int((df["status_label"].isin(["Resolved", "Closed"])).sum())
    resolved_pct = resolved / total * 100 if total else 0
    avg_sent = df["sentiment_score"].mean()
    real_services = df.loc[df[SERVICE_COL] != NOISE_SERVICE, SERVICE_COL]
    top_service = (
        real_services.value_counts(dropna=True).idxmax()
        if real_services.notna().any()
        else "—"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total tickets", f"{total:,}")
    c2.metric("Resolved / Closed", f"{resolved_pct:.1f}%", delta=f"{resolved:,}")
    c3.metric("Avg sentiment", f"{avg_sent:.1f}" if pd.notna(avg_sent) else "—",
              help="Freshdesk score 0–100; higher = more positive")
    c4.metric("Top service", str(top_service))

    st.markdown("### Daily ticket volume")
    daily = df.groupby("created_date").size().reset_index(name="tickets")
    fig = px.line(daily, x="created_date", y="tickets", markers=True)
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Top 10 services by ticket volume")
    st.caption("Excludes the automation/noise bucket so leadership sees real workload.")
    top = real_services.value_counts(dropna=True).head(10).reset_index()
    top.columns = ["service", "tickets"]
    fig2 = px.bar(top, x="tickets", y="service", orientation="h")
    fig2.update_layout(
        height=380, margin=dict(l=10, r=10, t=10, b=10),
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(fig2, use_container_width=True)
