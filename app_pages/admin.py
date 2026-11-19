"""Admin panel - only reachable by the administrator (see auth.is_admin)."""
import os

import pandas as pd
import streamlit as st

import auth
import glance_data as gd
import sql_agent
from common import check_database, shared_engine
from db_connector import sync_catalog

if not auth.is_admin():                      # the page is only in the menu for admins; this guards direct links
    st.error("This page is for the administrator only.")
    st.stop()

me = auth.current_user()
st.caption(f"Signed in as **{me['name']}** ({me['email']}) · administrator")

tab_users, tab_data, tab_system = st.tabs([":material/group: Users", ":material/database: Data",
                                           ":material/settings: System"])

# ---------------------------------------------------------------- users
with tab_users:
    users = auth.list_users()
    pending = [u for u in users if u[5] == "pending"]
    total, admins = len(users), sum(1 for u in users if u[2] == "admin")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accounts", total)
    c2.metric("Waiting for approval", len(pending))
    c3.metric("Approved", sum(1 for u in users if u[5] == "approved"))
    c4.metric("Blocked", sum(1 for u in users if u[5] == "blocked"))

    if pending:
        st.subheader(f"Waiting for approval ({len(pending)})")
        for name, email_, _, created, _, _ in pending:
            n, e, a, r = st.columns([3, 4, 1.5, 1.5], vertical_alignment="center")
            n.markdown(f"**{name}**")
            e.caption(f"{email_} · signed up {created:%d %b %Y}")
            if a.button("Approve", key=f"adm_ok_{email_}", icon=":material/check:", width="stretch"):
                auth.set_status(email_, "approved")
                st.rerun()
            if r.button("Reject", key=f"adm_no_{email_}", icon=":material/close:", width="stretch"):
                auth.delete_user(email_)
                st.rerun()

    st.subheader("All accounts")
    df = pd.DataFrame(users, columns=["Name", "Email", "Role", "Created", "Has password", "Status"])
    df["Sign-in"] = df["Has password"].map({True: "Email + password", False: "Google only"})
    st.dataframe(df[["Name", "Email", "Role", "Status", "Sign-in", "Created"]], width="stretch", hide_index=True)

    st.subheader("Manage an account")
    others = [u[1] for u in users if u[1] != auth.ADMIN_EMAIL]
    if not others:
        st.info("No other accounts yet. People appear here after they sign up.")
    else:
        email = st.selectbox("Account", others, key="adm_user")
        current_role = next(u[2] for u in users if u[1] == email)
        current_status = next(u[5] for u in users if u[1] == email)
        left, mid, right = st.columns(3)
        with left:
            status = st.selectbox("Access", list(auth.STATUSES), index=list(auth.STATUSES).index(current_status),
                                  key="adm_status", help="Only approved accounts can open the private pages.")
            if st.button("Save access", key="adm_save_status", width="stretch", disabled=status == current_status):
                st.error(err) if (err := auth.set_status(email, status)) else st.rerun()
            role = st.selectbox("Role", ["user", "admin"], index=["user", "admin"].index(current_role), key="adm_role")
            if st.button("Save role", key="adm_save_role", width="stretch", disabled=role == current_role):
                st.error(err) if (err := auth.set_role(email, role)) else st.rerun()
        with mid:
            new_pw = st.text_input("New password", type="password", key="adm_pw",
                                   help=f"At least {auth.MIN_PASSWORD} characters.")
            if st.button("Reset password", key="adm_reset", width="stretch"):
                if err := auth.set_password(email, new_pw):
                    st.error(err)
                else:
                    st.success("Password updated.")
        with right:
            st.write("")
            confirm = st.checkbox("I want to delete this account", key="adm_confirm_del")
            if st.button("Delete account", key="adm_delete", type="primary", width="stretch", disabled=not confirm):
                st.error(err) if (err := auth.delete_user(email)) else st.rerun()

# ---------------------------------------------------------------- data
with tab_data:
    ok, msg = check_database()
    (st.success if ok else st.error)(msg)
    if ok:
        cat = gd.catalog_table()
        a, b = st.columns(2)
        a.metric("Tables", len(cat))
        b.metric("Total rows", f"{int(cat['row_count'].sum()):,}")
        st.dataframe(cat[["table_name", "row_count", "column_count", "loaded_at", "file"]]
                     .rename(columns={"table_name": "Table", "row_count": "Rows", "column_count": "Columns",
                                      "loaded_at": "Loaded", "file": "Source"}),
                     width="stretch", hide_index=True, column_config={"Rows": st.column_config.NumberColumn(format="%,d")})
    if st.button("Refresh data from Supabase", icon=":material/refresh:", key="adm_refresh",
                 help="Registers new tables and clears the cached summaries."):
        try:
            sync_catalog(shared_engine())
            st.cache_data.clear()
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"Refresh failed: {str(e)[:200]}")

# ---------------------------------------------------------------- system
with tab_system:
    st.markdown(
        f"- **Chat model:** `{sql_agent.MODEL}`\n"
        f"- **Groq key:** {'set' if os.getenv('GROQ_API_KEY') else '**missing** - add GROQ_API_KEY to .env'}\n"
        f"- **Supabase URL:** {'set' if os.getenv('SUPABASE_DB_URL') else '**missing** - add SUPABASE_DB_URL to .env'}\n"
        f"- **Google sign-in:** {'configured' if auth.google_configured() else 'not configured (.streamlit/secrets.toml)'}")
    if st.button("Clear all caches", icon=":material/delete_sweep:", key="adm_clear"):
        st.cache_data.clear()
        st.toast("Caches cleared.")
