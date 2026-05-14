"""Branded sign-in screen and auth gate for the dashboard."""

from __future__ import annotations

import streamlit as st

from .auth import (
    ALLOWED_DOMAIN,
    SESSION_KEY,
    build_magic_link,
    is_allowed,
    make_token,
    send_magic_email,
    verify_token,
)


def _base_url() -> str:
    return st.secrets.get("app", {}).get("base_url", "http://localhost:8501")


_LOGIN_CSS = """
<style>
.adres-login {
  max-width: 480px;
  margin: 4rem auto;
  padding: 2.4rem 2.4rem 2rem 2.4rem;
  background: white;
  border: 1px solid #E5E0D2;
  border-top: 4px solid #B89968;
  border-radius: 6px;
  box-shadow: 0 6px 18px rgba(15, 45, 61, 0.08);
}
.adres-login h2 {
  margin: 0 0 0.35rem 0 !important;
  color: #0F2D3D !important;
  font-family: Georgia, 'Times New Roman', serif !important;
  font-size: 1.5rem !important;
}
.adres-login p.lede {
  color: #6B6B6B;
  font-style: italic;
  margin: 0 0 1.4rem 0;
}
.adres-login .note {
  color: #6B6B6B;
  font-size: 0.85rem;
  margin-top: 1rem;
  line-height: 1.5;
}
</style>
"""


def _render_login_card() -> None:
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="adres-login">
          <h2>Sign in to AccessRP Analytics</h2>
          <p class="lede">Enter your <b>@{ALLOWED_DOMAIN}</b> email — we'll send you a one-time sign-in link.</p>
        """,
        unsafe_allow_html=True,
    )

    with st.form("adres_login", clear_on_submit=False):
        email = st.text_input(
            "Work email",
            placeholder=f"name@{ALLOWED_DOMAIN}",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Send sign-in link",
                                          use_container_width=True)

    if submitted:
        email = (email or "").strip().lower()
        if not email:
            st.warning("Enter your email to continue.")
        elif not is_allowed(email):
            st.error(f"Only @{ALLOWED_DOMAIN} accounts can sign in to this dashboard.")
        else:
            try:
                token = make_token(email)
                link = build_magic_link(_base_url(), token)
                ok, mode = send_magic_email(email, link)
                if mode == "console":
                    st.success(
                        f"Sign-in link generated for **{email}**. "
                        "In dev mode the link is printed in the server console "
                        "instead of being emailed."
                    )
                else:
                    st.success(
                        f"Sign-in link sent to **{email}**. "
                        "Check your inbox (link expires in 15 minutes)."
                    )
            except Exception as e:
                st.error(f"Could not send sign-in link: {e}")

    st.markdown(
        '<div class="adres-login"><p class="note">'
        'Access is restricted to ADRES staff. This dashboard contains '
        'ADGM AccessRP support-ticket data — handle accordingly.'
        '</p></div>',
        unsafe_allow_html=True,
    )


def gate() -> str:
    """Block the rest of the app unless the user is signed in.

    Handles the magic-link callback (?token=...), session persistence, and
    rendering the sign-in screen. Returns the signed-in email.

    If [auth].bypass = true in secrets.toml, auth is skipped entirely and
    a placeholder identity is used. Intended for local dev only.
    """
    auth_cfg = st.secrets.get("auth", {})
    if auth_cfg.get("bypass", False):
        placeholder = auth_cfg.get("bypass_as", "dev@adres.ae")
        st.session_state[SESSION_KEY] = placeholder
        return placeholder

    if SESSION_KEY in st.session_state:
        return st.session_state[SESSION_KEY]

    params = st.query_params
    token = params.get("token")
    if token:
        email = verify_token(token)
        if email:
            st.session_state[SESSION_KEY] = email
            try:
                del st.query_params["token"]
            except KeyError:
                pass
            st.rerun()
        else:
            st.error("That sign-in link is invalid or has expired. "
                     "Request a new one below.")

    _render_login_card()
    st.stop()
    return ""  # unreachable


def sidebar_account_panel(email: str) -> None:
    """Render the signed-in user + sign-out button in the sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"<div style='color:#6B6B6B;font-size:0.85rem;'>Signed in as</div>"
        f"<div style='color:#0F2D3D;font-weight:600;font-size:0.95rem;"
        f"word-break:break-all;'>{email}</div>",
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Sign out", use_container_width=True):
        st.session_state.pop(SESSION_KEY, None)
        st.rerun()
