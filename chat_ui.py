"""Chat rendering + one chat turn, shared by the Chat page and the tile chat on At a glance."""
from datetime import datetime

import streamlit as st

import sql_agent


def render_message(message, idx, prefix="chat"):
    """Draw one chat message: text, SQL used, data preview and the Excel download button."""
    st.markdown(message["content"])
    if message.get("sql"):
        with st.expander("SQL used"):
            st.code(message["sql"], language="sql")
            if message.get("tables"):
                st.caption("Tables: " + ", ".join(message["tables"]))
    if message.get("data") is not None and not message["data"].empty:
        total = len(message["data"])
        with st.expander(f"Data ({total:,} rows)", expanded=False):
            st.dataframe(message["data"].head(sql_agent.PREVIEW_ROWS), width="stretch",
                         alt="Query result preview")
            if total > sql_agent.PREVIEW_ROWS:
                st.caption(f"Showing the first {sql_agent.PREVIEW_ROWS:,} rows. "
                           "The Excel download has all rows.")
        if message.get("truncated"):
            st.caption(f"Result limited to the first {sql_agent.MAX_ROWS:,} rows.")
        if message.get("xlsx"):
            st.download_button("Download Excel report", data=message["xlsx"],
                               file_name=message["xlsx_name"], key=f"{prefix}_dl_{idx}",
                               icon=":material/download:",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def answer(question, messages, allowed_tables=None, focus=None):
    """Run the question through the SQL agent and return the assistant message dict."""
    history = [{"role": m["role"], "content": m["content"]} for m in messages]
    try:
        with st.spinner("Thinking..."):
            r = sql_agent.ask(question, history, allowed_tables=allowed_tables, focus=focus)
        reply = {"role": "assistant", "content": r["answer"], "sql": r["sql"],
                 "data": r["data"], "tables": r["tables"], "truncated": r["truncated"]}
        if r["error"]:
            reply["content"] += f"\n\n_Last error: {r['error']}_"
        if r["data"] is not None and not r["data"].empty:
            reply["xlsx"] = sql_agent.to_excel_bytes(r["data"], r["sql"])
            reply["xlsx_name"] = f"BI_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    except Exception as e:  # noqa: BLE001
        reply = {"role": "assistant", "content": f"Something went wrong: {e}"}
    return reply
