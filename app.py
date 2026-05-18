"""ADGM AccessRP — Support Tickets Dashboard (Streamlit entrypoint)."""

from __future__ import annotations

import streamlit as st

from lib.auth_ui import gate, sidebar_account_panel
from lib.data import load_tickets
from lib.filters import render_sidebar_filters
from lib.tabs import complaints, overview, qualitative, report, root_cause, sentiment, volume
from lib.theme import CUSTOM_CSS, HEADER_HTML, install as install_theme

st.set_page_config(
    page_title="AccessRP Support Tickets",
    page_icon="📊",
    layout="wide",
)

install_theme()
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Auth gate — everything below only runs for signed-in @adres.ae users.
user_email = gate()

st.markdown(HEADER_HTML, unsafe_allow_html=True)

df = load_tickets()
filtered = render_sidebar_filters(df)
sidebar_account_panel(user_email)

tab_overview, tab_report, tab_complaints, tab_qual, tab_volume, tab_root, tab_sent = st.tabs(
    ["Overview", "Report", "Complaints", "Qualitative",
     "Volume & trends", "Root cause", "Sentiment"]
)

with tab_overview:
    overview.render(filtered)
with tab_report:
    report.render(filtered)
with tab_complaints:
    complaints.render(filtered)
with tab_qual:
    qualitative.render(filtered)
with tab_volume:
    volume.render(filtered)
with tab_root:
    root_cause.render(filtered)
with tab_sent:
    sentiment.render(filtered)
