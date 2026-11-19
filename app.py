"""
BI Assistant Bot - Green Delta Insurance, multi-page Streamlit app.

  Chat          app_pages/chat.py     ask questions about the registers, get Excel reports
  At a glance   app_pages/glance.py   one summary tile per register + the Ask pop-up
  Summary       app_pages/summary.py  year / class / customer comparison across selected registers

Run:  streamlit run app.py
"""
import streamlit as st

import sql_agent
from common import check_database

st.set_page_config(page_title="BI ASSISTANT BOT - Green Delta", page_icon="assets/gdic_icon.png",
                   layout="wide")
page = st.navigation(
    [
        st.Page("app_pages/chat.py", title="Chat", icon=":material/chat:", url_path="chat",
                help="Ask questions about the MIS registers in plain English, or paste a SQL query. "
                     "Download any result as an Excel report."),
        st.Page("app_pages/glance.py", title="At a glance", icon=":material/dashboard:",
                url_path="glance",
                help="Summary tiles for every register: rows, date coverage, headline totals and "
                     "when each file was last updated. Use Ask to question a register."),
        st.Page("app_pages/summary.py", title="Summary", icon=":material/bar_chart:",
                url_path="summary",
                help="Year-wise, class-wise and customer-wise premium, compared across the "
                     "registers you select, with stacked bar charts."),
        st.Page("app_pages/excel_reports.py", title="Excel reports", icon=":material/table_view:",
                url_path="excel",
                help="Department reports in your standard Excel format, and a pivot generator "
                     "that delivers plain values or live formulas."),
    ],
    position="top",
)

with st.sidebar:
    # the whole brand block sits in the middle of the sidebar, both across and down
    with st.container(key="brand"):
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.image("assets/gdic_logo.png", width=232, alt="Green Delta Insurance logo")
        st.subheader("BI ASSISTANT BOT", text_alignment="center")
        ok, msg = check_database()
        if ok:
            st.markdown(f":material/check_circle: {msg}", text_alignment="center")
        else:
            st.error(msg)
        st.caption(f"Model: {sql_agent.MODEL}", text_alignment="center")
    # Streamlit can't centre sidebar content vertically on its own (the sidebar has no fixed height),
    # so push just this block down by half the window height minus half the block's own height.
    st.html("<style>.st-key-brand { margin-top: calc(50vh - 162px); }</style>")

st.title(page.title, icon=page.icon)
page.run()
