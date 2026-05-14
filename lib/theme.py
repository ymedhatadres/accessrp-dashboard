"""AccessRP / ADGM-inspired brand theme for charts and UI."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# Brand palette
NAVY = "#0F2D3D"          # primary
NAVY_LIGHT = "#1F4A63"
GOLD = "#B89968"          # accent
GOLD_DEEP = "#8E6F44"
TEAL = "#2E7D6B"          # success / positive
AMBER = "#C7913D"         # warning / neutral
BRICK = "#B53A2C"         # negative / danger
SAND = "#F1ECE2"          # secondary bg
CREAM = "#FAFAF7"         # bg
INK = "#1A1A1A"           # text
MUTED = "#6B6B6B"

# Qualitative sequence used by px.bar / px.line / px.area when color is a category.
CATEGORICAL = [
    NAVY, GOLD, TEAL, AMBER, NAVY_LIGHT, GOLD_DEEP, BRICK, MUTED,
    "#4A6F84", "#7A5E3E", "#5C8E80", "#A57951",
]

# Sequential scale for heatmaps / continuous bars.
SEQUENTIAL_NAVY = [
    [0.0, CREAM],
    [0.25, "#D9D5C5"],
    [0.5, "#7A8E96"],
    [0.75, "#1F4A63"],
    [1.0, NAVY],
]

# Diverging scale for sentiment (low=red, mid=neutral, high=green-teal).
DIVERGING_SENTIMENT = [
    [0.0, BRICK],
    [0.35, AMBER],
    [0.55, "#D9D5C5"],
    [0.75, "#5C8E80"],
    [1.0, TEAL],
]

SENTIMENT_BUCKET_COLORS = {
    "Negative": BRICK,
    "Neutral": MUTED,
    "Positive": TEAL,
}


def _template() -> go.layout.Template:
    tpl = go.layout.Template()
    tpl.layout = go.Layout(
        font=dict(family="Georgia, 'Times New Roman', serif", color=INK, size=13),
        title=dict(font=dict(color=NAVY, size=16)),
        paper_bgcolor=CREAM,
        plot_bgcolor=CREAM,
        colorway=CATEGORICAL,
        xaxis=dict(
            gridcolor="#E5E0D2", zerolinecolor="#E5E0D2", linecolor="#C9C2B1",
            tickcolor="#C9C2B1", title=dict(font=dict(color=NAVY)),
        ),
        yaxis=dict(
            gridcolor="#E5E0D2", zerolinecolor="#E5E0D2", linecolor="#C9C2B1",
            tickcolor="#C9C2B1", title=dict(font=dict(color=NAVY)),
        ),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK)),
        coloraxis=dict(colorbar=dict(outlinewidth=0, tickcolor="#C9C2B1")),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return tpl


BRAND_TEMPLATE_NAME = "accessrp"


def install() -> None:
    """Register the brand template as the global Plotly default."""
    pio.templates[BRAND_TEMPLATE_NAME] = _template()
    pio.templates.default = BRAND_TEMPLATE_NAME


CUSTOM_CSS = """
<style>
:root {
  --brand-navy: #0F2D3D;
  --brand-gold: #B89968;
  --brand-sand: #F1ECE2;
  --brand-cream: #FAFAF7;
  --brand-ink: #1A1A1A;
  --brand-muted: #6B6B6B;
}

html, body, [class*="css"], .stApp {
  font-family: Georgia, 'Times New Roman', serif !important;
  color: var(--brand-ink) !important;
}

.stApp {
  background: var(--brand-cream) !important;
}

[data-testid="stSidebar"] {
  background: var(--brand-sand) !important;
  border-right: 1px solid #E5E0D2;
}

[data-testid="stSidebar"] * {
  color: var(--brand-ink) !important;
}

h1, h2, h3, h4 {
  color: var(--brand-navy) !important;
  font-weight: 600 !important;
  letter-spacing: -0.01em;
}

h1 {
  border-bottom: 3px solid var(--brand-gold);
  padding-bottom: 0.4rem;
  margin-bottom: 0.5rem;
}

[data-testid="stMetric"] {
  background: white;
  border: 1px solid #E5E0D2;
  border-left: 4px solid var(--brand-gold);
  border-radius: 4px;
  padding: 0.9rem 1rem;
  box-shadow: 0 1px 2px rgba(15, 45, 61, 0.04);
}

[data-testid="stMetricLabel"] {
  color: var(--brand-muted) !important;
  font-size: 0.85rem !important;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

[data-testid="stMetricValue"] {
  color: var(--brand-navy) !important;
  font-weight: 700 !important;
}

[data-testid="stMetricDelta"] {
  font-size: 0.85rem !important;
}

.stTabs [data-baseweb="tab-list"] {
  gap: 0;
  border-bottom: 1px solid #D9D2C2;
  background: transparent;
}

.stTabs [data-baseweb="tab"] {
  background: transparent;
  border-radius: 0;
  padding: 0.6rem 1.2rem;
  color: var(--brand-muted);
  font-weight: 500;
  border-bottom: 3px solid transparent;
  margin-bottom: -1px;
}

.stTabs [aria-selected="true"] {
  color: var(--brand-navy) !important;
  border-bottom-color: var(--brand-gold) !important;
  background: rgba(184, 153, 104, 0.08) !important;
}

[data-testid="stDataFrame"] {
  border: 1px solid #E5E0D2;
  border-radius: 4px;
}

.stButton > button, .stDownloadButton > button {
  background: var(--brand-navy);
  color: var(--brand-cream);
  border: 1px solid var(--brand-navy);
  border-radius: 3px;
  font-weight: 500;
}

.stButton > button:hover, .stDownloadButton > button:hover {
  background: var(--brand-gold);
  color: var(--brand-navy);
  border-color: var(--brand-gold);
}

.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div,
.stTextInput input,
.stDateInput input {
  border-radius: 3px !important;
  border: 1px solid #C9C2B1 !important;
  background: white !important;
}

[data-testid="stCaptionContainer"] {
  color: var(--brand-muted) !important;
  font-style: italic;
}

div[data-testid="stExpander"] {
  border: 1px solid #E5E0D2;
  border-radius: 4px;
  background: white;
}

div[data-testid="stExpander"] summary {
  color: var(--brand-navy);
  font-weight: 500;
}

hr {
  border-color: #D9D2C2 !important;
}
</style>
"""

HEADER_HTML = """
<div style="
  display:flex; align-items:center; gap:0.8rem;
  padding: 0.6rem 0 1rem 0;
  border-bottom: 1px solid #D9D2C2;
  margin-bottom: 1rem;
">
  <div style="
    width: 6px; height: 44px; background: #B89968; border-radius: 2px;
  "></div>
  <div>
    <div style="
      color: #0F2D3D; font-weight: 700; font-size: 1.55rem;
      font-family: Georgia, 'Times New Roman', serif;
      letter-spacing: -0.01em; line-height: 1.1;
    ">AccessRP &mdash; Support Tickets Analysis</div>
    <div style="
      color: #6B6B6B; font-size: 0.92rem; margin-top: 0.15rem;
      font-style: italic;
    ">ADGM real-estate services portal &middot; quarterly support-ticket analytics</div>
  </div>
</div>
"""
