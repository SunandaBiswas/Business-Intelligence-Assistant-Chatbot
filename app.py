"""
HR Assistant - Streamlit chat UI.

Run:  streamlit run app.py
"""
import streamlit as st

import sql_agent
from db_connector import get_engine

st.set_page_config(page_title="HR Assistant", page_icon="💬", layout="wide")

EXAMPLES = [
    "How many rows are in the collection register?",
    "Total premium collected by year from the collection register",
    "Which 10 branches had the highest claim payments?",
    "Show the target by distribution channel for 2023",
]


@st.cache_resource
def check_database():
    try:
        with get_engine().connect() as conn:
            n = conn.exec_driver_sql("SELECT COUNT(*) FROM sys.tables").scalar()
        return True, f"Connected to Register ({n} tables)"
    except Exception as e:  # noqa: BLE001
        return False, f"Database connection failed: {str(e)[:200]}"


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("💬 HR Assistant")
    ok, msg = check_database()
    (st.success if ok else st.error)(msg)
    st.caption(f"Model: {sql_agent.MODEL}")
    if st.button("🗑️ Clear chat", width="stretch"):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.markdown("**Try asking**")
    for ex in EXAMPLES:
        if st.button(ex, key=ex, width="stretch"):
            st.session_state.pending = ex

# ---------------------------------------------------------------- chat
st.header("Ask questions about your MIS registers")
st.session_state.setdefault("messages", [])


def render(msg):
    st.markdown(msg["content"])
    if msg.get("sql"):
        with st.expander("SQL used"):
            st.code(msg["sql"], language="sql")
            if msg.get("tables"):
                st.caption("Tables: " + ", ".join(msg["tables"]))
    if msg.get("data") is not None and not msg["data"].empty:
        with st.expander(f"Data ({len(msg['data'])} rows)", expanded=False):
            st.dataframe(msg["data"], width="stretch")
        if msg.get("truncated"):
            st.caption(f"Showing the first {sql_agent.MAX_ROWS} rows only.")


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        render(m)

question = st.chat_input("Ask about collections, renewals, claims, targets...")
question = question or st.session_state.pop("pending", None)

if question:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        if not ok:
            reply = {"role": "assistant", "content": msg}
        else:
            try:
                with st.spinner("Thinking..."):
                    r = sql_agent.ask(question, history)
                reply = {"role": "assistant", "content": r["answer"], "sql": r["sql"],
                         "data": r["data"], "tables": r["tables"], "truncated": r["truncated"]}
                if r["error"]:
                    reply["content"] += f"\n\n_Last error: {r['error']}_"
            except Exception as e:  # noqa: BLE001
                reply = {"role": "assistant", "content": f"⚠️ {e}"}
        render(reply)
    st.session_state.messages.append(reply)
