"""Cached parquet loader for the dashboard.

The parquet file is not committed to the public code repo because it contains
customer PII. There are two ways the file can reach the app:

1. **Local dev**: run `python preprocess.py` to generate it at the path below.
2. **Streamlit Cloud / any deploy**: configure a `[data]` block in
   .streamlit/secrets.toml pointing at a private GitHub repo holding the
   parquet. The app downloads it on first load.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pandas as pd
import streamlit as st

PARQUET_PATH = Path(__file__).resolve().parent.parent / "data" / "tickets.parquet"

SERVICE_COL = "custom_fields.cf_service"
PRODUCT_COL = "custom_fields.cf_products"
ROOT_CAUSE_COL = "custom_fields.cf_root_cause"
ISSUE_SOURCE_COL = "custom_fields.cf_issue_source"
AREA_COL = "custom_fields.cf_area_of_impact"
PLATFORM_COL = "custom_fields.cf_platform"
SEVERITY_COL = "custom_fields.cf_severity"


def _download_parquet() -> None:
    """Fetch the parquet from a private GitHub repo into PARQUET_PATH.

    Requires .streamlit/secrets.toml to contain:

        [data]
        repo = "ymedhatadres/accessrp-data"   # owner/name of the private repo
        path = "tickets.parquet"              # path within that repo
        ref  = "main"                         # branch or tag
        token = "<PAT with read access>"      # fine-grained token, repo: contents read
    """
    cfg = st.secrets.get("data", None)
    if not cfg:
        raise FileNotFoundError(
            f"{PARQUET_PATH} not found and no [data] secrets configured. "
            "Run `python preprocess.py` locally, or add a [data] block to "
            ".streamlit/secrets.toml so the app can download it."
        )

    missing = [k for k in ("repo", "path", "token") if not cfg.get(k)]
    if missing:
        raise RuntimeError(
            "Missing [data] secret(s): " + ", ".join(missing)
        )

    repo = cfg["repo"]
    path = cfg["path"]
    ref = cfg.get("ref", "main")
    token = cfg["token"]

    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw",
            "User-Agent": "accessrp-dashboard",
        },
    )

    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(
            PARQUET_PATH, "wb"
        ) as f:
            f.write(resp.read())
    except Exception as e:
        raise RuntimeError(
            f"Failed to download parquet from {repo}@{ref}:{path}: {e}"
        ) from e


@st.cache_data(show_spinner="Loading tickets...")
def load_tickets() -> pd.DataFrame:
    """Load the parquet and return only real complaints.

    Noise rows (auto-replies, delivery failures, the 'Ads Test Tickets and
    Auto-Emails' service) are dropped at load time. Themes are pre-attached
    so individual tabs don't need to reclassify.
    """
    if not PARQUET_PATH.exists():
        _download_parquet()
    df = pd.read_parquet(PARQUET_PATH)

    # Local import to avoid circular dependency at module-import time.
    from .themes import classify
    df = classify(df)
    df = df.loc[~df["is_noise"]].reset_index(drop=True)
    return df
