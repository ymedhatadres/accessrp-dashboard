"""Sidebar filters shared across all tabs."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .data import SERVICE_COL


def _sorted_unique(series: pd.Series) -> list[str]:
    return sorted(series.dropna().astype(str).unique().tolist())


def render_sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")

    quarters_avail = (
        _sorted_unique(df["quarter"]) if "quarter" in df.columns else []
    )
    quarters = (
        st.sidebar.multiselect(
            "Quarter",
            options=quarters_avail,
            default=[],
            help="Empty = all quarters",
        )
        if quarters_avail
        else []
    )

    # Date-range bounds narrow to the selected quarter(s) if any picked.
    bounds_df = (
        df[df["quarter"].astype(str).isin(quarters)] if quarters else df
    )
    min_d = bounds_df["created_at"].min().date()
    max_d = bounds_df["created_at"].max().date()
    date_range = st.sidebar.date_input(
        "Created date range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
    )
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
    else:
        start, end = min_d, max_d

    services = st.sidebar.multiselect(
        "Service",
        options=_sorted_unique(df[SERVICE_COL]),
        default=[],
        help="Empty = all services",
    )
    statuses = st.sidebar.multiselect(
        "Status",
        options=_sorted_unique(df["status_label"]),
        default=[],
    )
    sources = st.sidebar.multiselect(
        "Source",
        options=_sorted_unique(df["source_label"]),
        default=[],
    )
    priorities = st.sidebar.multiselect(
        "Priority",
        options=_sorted_unique(df["priority_label"]),
        default=[],
    )

    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    mask = (df["created_at"] >= start_ts) & (df["created_at"] < end_ts)
    if quarters:
        mask &= df["quarter"].astype(str).isin(quarters)
    if services:
        mask &= df[SERVICE_COL].astype(str).isin(services)
    if statuses:
        mask &= df["status_label"].astype(str).isin(statuses)
    if sources:
        mask &= df["source_label"].astype(str).isin(sources)
    if priorities:
        mask &= df["priority_label"].astype(str).isin(priorities)

    filtered = df.loc[mask]

    st.sidebar.markdown("---")
    st.sidebar.metric("Tickets in view", f"{len(filtered):,}", delta=f"of {len(df):,}")
    return filtered
