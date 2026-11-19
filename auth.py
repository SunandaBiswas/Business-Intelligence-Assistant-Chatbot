"""
Log in / Sign up for the BI Assistant Bot.

  * Email + password : accounts live in a local SQLite file (users.db, git-ignored).
                       Passwords are never stored - only a salted scrypt hash.
  * Google           : Streamlit's built-in OpenID Connect login (st.login). It needs a one-time
                       setup in .streamlit/secrets.toml - see .streamlit/secrets.toml.example.

app.py calls render_auth_bar() once; it draws the buttons in the top-right corner.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
from pathlib import Path

import streamlit as st

DB_PATH = Path(__file__).with_name("users.db")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


# ---- user store -------------------------------------------------------------
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users ("
                 "email TEXT PRIMARY KEY, name TEXT, salt BLOB, pw_hash BLOB, "
                 "created TEXT DEFAULT CURRENT_TIMESTAMP)")
    if "role" not in [r[1] for r in conn.execute("PRAGMA table_info(users)")]:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    return conn


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def create_user(name: str, email: str, password: str):
    """Returns an error message, or None on success."""
    email = email.strip().lower()
    if not name.strip():
        return "Please enter your name."
    if not EMAIL_RE.match(email):
        return "Please enter a valid email address."
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    salt = secrets.token_bytes(16)
    try:
        with _db() as conn:
            conn.execute("INSERT INTO users (email, name, salt, pw_hash) VALUES (?,?,?,?)",
                         (email, name.strip(), salt, _hash(password, salt)))
    except sqlite3.IntegrityError:
        return "An account with this email already exists - try logging in."
    return None


def check_user(email: str, password: str):
    """Returns the user's name if the credentials are right, otherwise None."""
    with _db() as conn:
        row = conn.execute("SELECT name, salt, pw_hash FROM users WHERE email = ?",
                           (email.strip().lower(),)).fetchone()
    if row and row[1] and hmac.compare_digest(_hash(password, row[1]), row[2]):
        return row[0]
    return None


# ---- who is logged in -------------------------------------------------------
def google_configured() -> bool:
    try:
        cid = st.secrets["auth"]["google"]["client_id"]
        return bool(cid) and not cid.startswith("xxxx") and not cid.startswith("PASTE")
    except Exception:  # noqa: BLE001  (no secrets file, or Google section not filled in)
        return False


def current_user():
    """{'name', 'email'} of whoever is logged in (Google or email), else None."""
    user = st.session_state.get("auth_user")
    if not user and google_configured() and getattr(st.user, "is_logged_in", False):
        user = {"name": st.user.get("name") or st.user.get("email"),
                "email": (st.user.get("email") or "").lower()}
        with _db() as conn:   # first Google login registers the person as a normal user
            conn.execute("INSERT OR IGNORE INTO users (email, name) VALUES (?,?)",
                         (user["email"], user["name"]))
    return user


def logout():
    st.session_state.pop("auth_user", None)
    if google_configured() and getattr(st.user, "is_logged_in", False):
        st.logout()


# ---- dialogs ----------------------------------------------------------------
def _google_button(label):
    if google_configured():
        st.button(label, icon=":material/account_circle:", width="stretch",
                  on_click=st.login, args=("google",))
    else:
        st.button(label, icon=":material/account_circle:", width="stretch", disabled=True,
                  help="Google sign-in isn't set up yet - see .streamlit/secrets.toml.example")


@st.dialog("Log in")
def login_dialog():
    _google_button("Continue with Google")
    st.caption("or use your email", text_alignment="center")
    with st.form("login_form", border=False):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary", width="stretch"):
            name = check_user(email, password)
            if name:
                st.session_state["auth_user"] = {"name": name, "email": email.strip().lower()}
                st.rerun()
            st.error("Wrong email or password.")


@st.dialog("Sign up")
def signup_dialog():
    _google_button("Sign up with Google")
    st.caption("or create an account with your email", text_alignment="center")
    with st.form("signup_form", border=False):
        name = st.text_input("Full name")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password",
                                 help=f"At least {MIN_PASSWORD} characters.")
        confirm = st.text_input("Confirm password", type="password")
        if st.form_submit_button("Create account", type="primary", width="stretch"):
            if password != confirm:
                st.error("The two passwords don't match.")
            elif err := create_user(name, email, password):
                st.error(err)
            else:
                st.session_state["auth_user"] = {"name": name.strip(),
                                                 "email": email.strip().lower()}
                st.rerun()


# ---- sidebar block ----------------------------------------------------------
def render_auth_bar():
    """Log in / Sign up buttons - or the user's details and Log out - for the sidebar, under the logo."""
    user = current_user()
    if user:
        st.markdown(f"**User Name:** {user['name']}  \n**Email:** {user['email']}", text_alignment="center")
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.button("Log out", on_click=logout, key="logout_btn", icon=":material/logout:")
    else:
        with st.container(horizontal=True, horizontal_alignment="center"):
            if st.button("Log in", key="login_btn"):
                login_dialog()
            if st.button("Sign up", key="signup_btn", type="primary"):
                signup_dialog()
