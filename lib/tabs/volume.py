"""Volume & trends tab."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..data import PRODUCT_COL, SERVICE_COL
from ..theme import SEQUENTIAL_NAVY


def render(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No tickets match the current filters.")
        return

    st.markdown("### Daily volume by status")
    daily = (
        df.groupby(["created_date", "status_label"]).size().reset_index(name="tickets")
    )
    fig = px.area(daily, x="created_date", y="tickets", color="status_label",
                  groupnorm=None)
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                      legend_title="Status")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Weekly volume")
    weekly = df.groupby("created_week").size().reset_index(name="tickets")
    fig_w = px.bar(weekly, x="created_week", y="tickets")
    fig_w.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_w, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Tickets by service")
        s = df[SERVICE_COL].value_counts(dropna=True).head(15).reset_index()
        s.columns = ["service", "tickets"]
        fig_s = px.bar(s, x="tickets", y="service", orientation="h")
        fig_s.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                            yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_s, use_container_width=True)
    with c2:
        st.markdown("### Tickets by source")
        src = df["source_label"].value_counts(dropna=False).reset_index()
        src.columns = ["source", "tickets"]
        fig_src = px.bar(src, x="tickets", y="source", orientation="h")
        fig_src.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                              yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig_src, use_container_width=True)

    st.markdown("### Tickets by product")
    p = df[PRODUCT_COL].value_counts(dropna=True).reset_index()
    p.columns = ["product", "tickets"]
    st.dataframe(p, use_container_width=True, hide_index=True)

    st.markdown("### When are tickets created? (hour × weekday)")
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                     "Saturday", "Sunday"]
    heat = (
        df.groupby(["created_weekday", "created_hour"]).size().reset_index(name="tickets")
    )
    heat["created_weekday"] = pd.Categorical(heat["created_weekday"],
                                             categories=weekday_order, ordered=True)
    pivot = heat.pivot(index="created_weekday", columns="created_hour", values="tickets").fillna(0)
    pivot = pivot.reindex(weekday_order)
    fig_h = px.imshow(pivot, aspect="auto", color_continuous_scale=SEQUENTIAL_NAVY,
                      labels=dict(x="Hour of day (UTC)", y="Weekday", color="Tickets"))
    fig_h.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_h, use_container_width=True)
