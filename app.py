"""
BI Assistant Bot - Green Delta Insurance, multi-page Streamlit app.

  Chat          app_pages/chat.py     ask questions about the registers, get Excel reports
  At a glance   app_pages/glance.py   one summary tile per register + the Ask pop-up
  Summary       app_pages/summary.py  year / class / customer comparison across selected registers

Run:  streamlit run app.py
"""
import streamlit as st

from auth import account_status, current_user, has_access, is_admin, render_auth_bar

st.set_page_config(page_title="BUSINESS INTELLIGENCE ASSISTANT BOT - Green Delta", page_icon="assets/gdic_icon.png",
                   layout="wide")
logged_in = has_access()                  # logged in AND approved by the administrator
ANNUAL_REPORT_URL = "https://green-delta.com/financial_indicator/annual-reports/"


def welcome_page():
    """What a visitor sees before logging in (log in with the sidebar buttons)."""
    status = account_status() if current_user() else None
    if status == "pending":
        st.info(
            "Your account is waiting for the administrator's approval.",
            icon=":material/hourglass_top:",
        )
    elif status == "blocked":
        st.error(
            "This account has been blocked. Please contact the administrator.",
            icon=":material/block:",
        )
    else:
        st.info(
            "Use **Log in** or **Sign up** in the sidebar to get started.",
            icon=":material/login:",
        )


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
pages.insert(0, st.Page("app_pages/public_chat.py", title="Public Chat",
                        icon=":material/public:", url_path="public-chat",
                        help="Ask about publicly available Green Delta Insurance annual reports and website information.",
                        default=False))
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
        render_auth_bar()                      # Log in / Sign up sit at the bottom of the block
    # Streamlit can't centre sidebar content vertically on its own (the sidebar has no fixed height),
    # so push just this block down by half the window height minus half the block's own height.
    st.html("<style>.st-key-brand { margin-top: calc(50vh - 215px); }</style>")

st.html(f"""
<style>
  .gdic-public-actions {{
    position: fixed;
    top: 0.45rem;
    right: 1rem;
    z-index: 100000;
  }}
  .gdic-public-actions a {{
    display: inline-block;
    color: #0b4f46;
    background: #ffffff;
    border: 1px solid #d8e5e2;
    border-radius: 8px;
    padding: 0.38rem 0.7rem;
    font-size: 0.82rem;
    font-weight: 650;
    text-decoration: none;
  }}
  .gdic-public-actions a:hover {{
    color: #ffffff;
    background: #0b6b5c;
  }}
  @media (max-width: 700px) {{
    .gdic-public-actions {{
      top: 3.35rem;
      right: 0.55rem;
    }}
  }}
</style>
<div class="gdic-public-actions">
  <a href="{ANNUAL_REPORT_URL}" target="_blank" rel="noopener noreferrer">Annual Report_GDIC</a>
</div>
""")

if page.url_path != "public-chat":
    st.title(page.title, icon=page.icon)
page.run()
