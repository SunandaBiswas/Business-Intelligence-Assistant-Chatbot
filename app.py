"""
BI Assistant Bot - Green Delta Insurance, multi-page Streamlit app.

  Chat          app_pages/chat.py     ask questions about the registers, get Excel reports
  At a glance   app_pages/glance.py   one summary tile per register + the Ask pop-up
  Summary       app_pages/summary.py  year / class / customer comparison across selected registers

Run:  streamlit run app.py
"""
import streamlit as st

import sql_agent
from auth import account_status, current_user, has_access, is_admin, render_auth_bar
from common import check_database

st.set_page_config(page_title="BUSINESS INTELLIGENCE ASSISTANT BOT - Green Delta", page_icon="assets/gdic_icon.png",
                   layout="wide")
logged_in = has_access()                  # logged in AND approved by the administrator


def welcome_page():
    """What a visitor sees before logging in (log in with the sidebar buttons)."""
    st.title("Welcome!")
    status = account_status() if current_user() else None
    if status == "pending":
        st.info("Your account is waiting for the administrator's approval. "
                "You'll be able to start as soon as it is approved.", icon=":material/hourglass_top:")
    elif status == "blocked":
        st.error("This account has been blocked. Please contact the administrator.", icon=":material/block:")
    else:
        st.info("Use **Log in** or **Sign up** in the sidebar to get started.", icon=":material/login:")


# (file, title, icon, url, help) - every page needs a login (approved account)
PRIVATE = [
    ("app_pages/chat.py", "Chat", ":material/chat:", "chat",
     "Ask questions about the MIS registers in plain English, or paste a SQL query. "
     "Download any result as an Excel report."),
    ("app_pages/glance.py", "At a glance", ":material/dashboard:", "glance",
     "Summary tiles for every register: rows, date coverage, headline totals and when each file was "
     "last updated. Use Ask to question a register."),
    ("app_pages/summary.py", "Summary", ":material/bar_chart:", "summary",
     "Year-wise, class-wise and customer-wise premium, compared across the registers you select, "
     "with stacked bar charts."),
    ("app_pages/excel_reports.py", "Excel reports", ":material/table_view:", "excel",
     "Department reports in your standard Excel format, and a pivot generator that delivers plain "
     "values or live formulas."),
]
if logged_in:
    pages = [st.Page(path, title=title, icon=icon, url_path=url, help=hint, default=(url == "chat"))
             for path, title, icon, url, hint in PRIVATE]
else:                                                  # before login: only the Welcome page, no locked tabs
    pages = [st.Page(welcome_page, title="Welcome", icon=":material/waving_hand:", url_path="welcome",
                     default=True)]
if is_admin():                                       # the Admin page only exists in the menu for the administrator
    pages.append(st.Page("app_pages/admin.py", title="Admin", icon=":material/admin_panel_settings:",
                         url_path="admin", help="Manage accounts, check the data and system status."))
page = st.navigation(pages, position="top")

with st.sidebar:
    # the whole brand block sits in the middle of the sidebar, both across and down
    with st.container(key="brand"):
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.image("assets/gdic_logo.png", width=232, alt="Green Delta Insurance logo")
        st.subheader("BUSINESS INTELLIGENCE ASSISTANT BOT", text_alignment="center")
        ok, msg = check_database()
        if ok:
            st.markdown(f":material/check_circle: {msg}", text_alignment="center")
        else:
            st.error(msg)
        st.caption(f"Model: {sql_agent.MODEL}", text_alignment="center")
        render_auth_bar()                      # Log in / Sign up sit at the bottom of the block
    # Streamlit can't centre sidebar content vertically on its own (the sidebar has no fixed height),
    # so push just this block down by half the window height minus half the block's own height.
    st.html("<style>.st-key-brand { margin-top: calc(50vh - 215px); }</style>")

st.title(page.title, icon=page.icon)
page.run()
