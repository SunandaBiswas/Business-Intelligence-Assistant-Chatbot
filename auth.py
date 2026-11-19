"""
Log in / Sign up for the BI Assistant Bot.

  * Accounts live in the Supabase database (table public._users), so they survive hosting and restarts.
    Passwords are never stored - only a salted scrypt hash.
  * Every new account starts as 'pending'. The administrator approves it in the Admin panel; only
    approved accounts can open the private pages (status: approved / pending / blocked).
  * Google: Streamlit's built-in OpenID Connect login (st.login). It needs a one-time setup in
    .streamlit/secrets.toml - see .streamlit/secrets.toml.example.

app.py calls render_auth_bar() once; it draws the buttons in the sidebar.
"""
import hashlib
import hmac
import os
import re
import secrets

import streamlit as st
from dotenv import load_dotenv

from common import shared_engine

TABLE = os.getenv("USERS_TABLE") or "_users"        # USERS_TABLE: optional override (tests)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8
ADMIN_NAME = "Sunanda Biswas"
ADMIN_EMAIL = "projectdata2698@gmail.com"      # the one administrator; sign-up with this email is blocked
STATUSES = ("approved", "pending", "blocked")
_ready = set()


# ---- user store -------------------------------------------------------------
def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def _run(sql, params=(), fetch=None):
    """Run one statement on the shared Supabase engine (committed). fetch: 'one' | 'all' | None."""
    _setup()
    with shared_engine().begin() as conn:
        res = conn.exec_driver_sql(sql, tuple(params)) if params else conn.exec_driver_sql(sql)
        return res.fetchone() if fetch == "one" else res.fetchall() if fetch == "all" else None


def _setup():
    """Create the users table once per process, and make sure the administrator account exists."""
    if TABLE in _ready:
        return
    load_dotenv(override=True)
    password = os.getenv("ADMIN_PASSWORD", "")
    salt = secrets.token_bytes(16) if password else None
    with shared_engine().begin() as conn:
        conn.exec_driver_sql(
            f'CREATE TABLE IF NOT EXISTS public."{TABLE}" ('
            "email text PRIMARY KEY, name text, salt bytea, pw_hash bytea, "
            "role text NOT NULL DEFAULT 'user', status text NOT NULL DEFAULT 'pending', "
            "created timestamp NOT NULL DEFAULT now())")
        row = conn.exec_driver_sql(f'SELECT 1 FROM public."{TABLE}" WHERE email = %s', (ADMIN_EMAIL,)).fetchone()
        if row is None:           # the administrator's password comes from ADMIN_PASSWORD (.env / hosting secrets)
            conn.exec_driver_sql(
                f'INSERT INTO public."{TABLE}" (email, name, salt, pw_hash, role, status) '
                "VALUES (%s,%s,%s,%s,'admin','approved')",
                (ADMIN_EMAIL, ADMIN_NAME, salt, _hash(password, salt) if password else None))
        else:
            conn.exec_driver_sql(f"UPDATE public.\"{TABLE}\" SET role = 'admin', status = 'approved' "
                                 "WHERE email = %s", (ADMIN_EMAIL,))
    _ready.add(TABLE)


@st.cache_data(ttl=15, show_spinner=False)
def _record(email):
    """(name, role, status) of an account, or None. Cached for 15 seconds so reruns stay fast."""
    row = _run(f'SELECT name, role, status FROM public."{TABLE}" WHERE email = %s', (email,), fetch="one")
    return tuple(row) if row else None


def create_user(name: str, email: str, password: str):
    """Returns an error message, or None on success. New accounts wait for the administrator's approval."""
    email = email.strip().lower()
    if not name.strip():
        return "Please enter your name."
    if not EMAIL_RE.match(email):
        return "Please enter a valid email address."
    if email == ADMIN_EMAIL:
        return "This email belongs to the administrator account - please log in instead."
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if _run(f'SELECT 1 FROM public."{TABLE}" WHERE email = %s', (email,), fetch="one"):
        return "An account with this email already exists - try logging in."
    salt = secrets.token_bytes(16)
    try:
        _run(f'INSERT INTO public."{TABLE}" (email, name, salt, pw_hash) VALUES (%s,%s,%s,%s)',
             (email, name.strip(), salt, _hash(password, salt)))
    except Exception:  # noqa: BLE001 - e.g. two sign-ups with the same email at once
        return "An account with this email already exists - try logging in."
    _record.clear()
    return None


def check_user(email: str, password: str):
    """Returns the user's name if the credentials are right, otherwise None."""
    row = _run(f'SELECT name, salt, pw_hash FROM public."{TABLE}" WHERE email = %s',
               (email.strip().lower(),), fetch="one")
    if row and row[1] and row[2] and hmac.compare_digest(_hash(password, bytes(row[1])), bytes(row[2])):
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
        email = (st.user.get("email") or "").lower()
        if not email or st.user.get("email_verified") is False:
            st.logout()
            return None
        user = {"name": st.user.get("name") or email, "email": email}
        if _record(email) is None:       # first Google login: registers the person, waiting for approval
            _run(f'INSERT INTO public."{TABLE}" (email, name) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                 (email, user["name"]))
            _record.clear()
    return user


def account_status(user=None):
    """'approved' | 'pending' | 'blocked' for the logged-in person (None when nobody is logged in)."""
    user = user or current_user()
    rec = _record(user["email"]) if user else None
    return rec[2] if rec else None


def has_access(user=None) -> bool:
    """True when the person is logged in AND approved: only they may open the private pages."""
    return account_status(user) == "approved"


def is_admin(user=None) -> bool:
    """True when the logged-in person has the admin role (checked in the user store, not the session)."""
    user = user or current_user()
    rec = _record(user["email"]) if user else None
    return bool(rec) and rec[1] == "admin" and rec[2] == "approved"


# ---- admin operations (used by app_pages/admin.py) ---------------------------
def list_users():
    """name, email, role, created, has_password, status"""
    return _run("SELECT name, email, role, created, pw_hash IS NOT NULL, status "
                f"FROM public.\"{TABLE}\" ORDER BY (role = 'admin') DESC, (status = 'pending') DESC, created",
                fetch="all")


def _update(sql, params):
    _run(sql, params)
    _record.clear()


def set_role(email, role):
    if email == ADMIN_EMAIL:
        return "The main administrator's role can't be changed."
    _update(f'UPDATE public."{TABLE}" SET role = %s WHERE email = %s', (role, email))
    return None


def set_status(email, status):
    if email == ADMIN_EMAIL:
        return "The main administrator's access can't be changed."
    if status not in STATUSES:
        return "Unknown status."
    _update(f'UPDATE public."{TABLE}" SET status = %s WHERE email = %s', (status, email))
    return None


def set_password(email, password):
    """Returns an error message, or None on success."""
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    salt = secrets.token_bytes(16)
    _update(f'UPDATE public."{TABLE}" SET salt = %s, pw_hash = %s WHERE email = %s',
            (salt, _hash(password, salt), email))
    return None


def delete_user(email):
    if email == ADMIN_EMAIL:
        return "The main administrator can't be deleted."
    _update(f'DELETE FROM public."{TABLE}" WHERE email = %s', (email,))
    return None


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
            if name and account_status({"email": email.strip().lower()}) == "blocked":
                st.error("This account has been blocked. Please contact the administrator.")
            elif name:
                st.session_state["auth_user"] = {"name": name, "email": email.strip().lower()}
                st.rerun()
            else:
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
        status = account_status(user)
        if status == "pending":
            st.caption(":material/hourglass_top: Waiting for the administrator's approval", text_alignment="center")
        elif status == "blocked":
            st.caption(":material/block: This account is blocked", text_alignment="center")
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.button("Log out", on_click=logout, key="logout_btn", icon=":material/logout:")
    else:
        with st.container(horizontal=True, horizontal_alignment="center"):
            if st.button("Log in", key="login_btn"):
                login_dialog()
            if st.button("Sign up", key="signup_btn"):
                signup_dialog()
