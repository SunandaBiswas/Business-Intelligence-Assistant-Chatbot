import streamlit as st

from chat_ui import answer, render_message
from common import check_database

EXAMPLES = [
    "How many rows are in the collection register?",
    "Total premium collected by year from the collection register",
    "Which 10 branches had the highest claim payments?",
    "Show the target by distribution channel for 2023",
]

ok, msg = check_database()
st.session_state.setdefault("messages", [])


def pick_example():
    """A clicked example becomes the next question; clear the pill so it can be clicked again."""
    st.session_state.pending = st.session_state.chat_examples
    st.session_state.chat_examples = None


# ---------------------------------------------------------------- header (the sidebar is kept for the logo)
st.caption("Ask questions about your MIS registers in plain English, "
           "or paste a SQL query to get its output as an Excel report. "
           "To ask about one specific register, use **Ask a question** on the At a glance page.")

suggestions = st.empty()                    # placeholder, so the pills can vanish the moment a question is asked
if not st.session_state.messages:
    suggestions.pills("Try asking", EXAMPLES, key="chat_examples", on_change=pick_example,
                      help="Click one to ask it, or type your own question below.")

for i, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"]):
        render_message(m, i)

# the chat box and Clear chat share one row pinned to the bottom of the page: button in the right corner
with st.bottom:
    bar, clear_col = st.columns([8, 1.5], vertical_alignment="center")
    with bar:
        question = st.chat_input("Ask about collections, renewals, claims, targets...")
    if clear_col.button("Clear chat", icon=":material/delete:", width="stretch", key="chat_clear"):
        st.session_state.messages = []
        st.rerun()
question = question or st.session_state.pop("pending", None)

if question:
    suggestions.empty()
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        reply = {"role": "assistant", "content": msg} if not ok else answer(question, history)
        render_message(reply, len(st.session_state.messages))
    st.session_state.messages.append(reply)
