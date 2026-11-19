import pandas as pd
import streamlit as st

import glance_data as gd
from chat_ui import answer, render_message
from common import check_database
from suggestions import suggestions_for

ok, msg = check_database()
if not ok:
    st.error(msg, title="Database not reachable")
    st.stop()

regs = gd.registers()
ALL = "All registers"


def fmt_date(ts, fmt="%d %b %Y"):
    return "—" if pd.isna(ts) else pd.Timestamp(ts).strftime(fmt)


# ---------------------------------------------------------------- Ask pop-up
@st.dialog("Ask about your registers", width="large")
def ask_dialog():
    """Pick a register (or all), choose a suggested question or type your own."""
    data = gd.registers()
    order = {c: i for i, c in enumerate(gd.CATEGORY_ORDER)}
    names = (data.assign(_o=data["category"].map(order)).sort_values(["_o", "name"])["name"].tolist())
    tables_of = dict(zip(data["name"], data["tables"]))
    category_of = dict(zip(data["name"], data["category"]))

    scope = st.selectbox(
        "Register", [ALL] + names, key="glance_ask_register",
        format_func=lambda n: n if n == ALL else f"{category_of[n]} · {n}",
        help="Choose the register your question is about, or All registers.")
    tables = None if scope == ALL else list(tables_of[scope])
    category = None if scope == ALL else category_of[scope]

    state_key = "glance_chat_" + (tables[0] if tables else "all")
    messages = st.session_state.setdefault(state_key, [])
    pill_key, pending_key = f"{state_key}_suggest", f"{state_key}_pending"

    def pick_suggestion():
        st.session_state[pending_key] = st.session_state[pill_key]
        st.session_state[pill_key] = None            # so it can be picked again later

    for i, m in enumerate(messages):
        with st.chat_message(m["role"]):
            render_message(m, i, prefix=state_key)

    st.pills("Suggested questions", suggestions_for(category), key=pill_key,
             on_change=pick_suggestion,
             help="Click one to ask it, or type your own question below.")
    if messages and st.button("Clear conversation", icon=":material/delete:", key=f"{state_key}_clear"):
        messages.clear()
        st.rerun(scope="fragment")

    prompt = st.chat_input(f"Ask about {scope}...", key=f"{state_key}_input") \
        or st.session_state.pop(pending_key, None)
    if prompt:
        history = list(messages)
        messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            reply = answer(prompt, history, allowed_tables=tables, focus=scope if tables else None)
            render_message(reply, len(messages), prefix=state_key)
        messages.append(reply)


top_text, top_button = st.columns([4, 1], vertical_alignment="center")
top_text.caption("One tile per register loaded into the Register database. "
                 "Figures update after each data load (daily at 7 AM). "
                 "Click **Ask a question** to choose a register and ask about it.")
if top_button.button("Ask a question", icon=":material/chat:", key="ask_open", type="primary",
                     width="stretch"):
    ask_dialog()

# ---------------------------------------------------------------- headline strip
with st.grid(4, gap="medium"):
    st.metric("Registers", f"{len(regs):,}", border=True, height="stretch",
              help="Source files loaded into the database (a file can hold several sheets).")
    st.metric("Tables", f"{int(regs['sheets'].sum()):,}", border=True, height="stretch",
              help="One database table per sheet / CSV file.")
    st.metric("Total rows", gd.compact(regs["rows"].sum()), border=True, height="stretch",
              help="Rows across all registers. Some registers overlap (for example copies and merged files).")
    st.metric("Last data load", fmt_date(regs["loaded"].max()), border=True, height="stretch",
              help=f"Loaded at {fmt_date(regs['loaded'].max(), '%d %b %Y, %H:%M')}")

# ---------------------------------------------------------------- filters
categories = [c for c in gd.CATEGORY_ORDER if c in set(regs["category"])]
f1, f2 = st.columns([3, 2], vertical_alignment="bottom")
with f1:
    picked = st.pills("Register type", categories, selection_mode="multi", default=categories,
                      key="glance_categories")
with f2:
    search = st.text_input("Search registers", placeholder="e.g. collection 2025, claim, banca",
                           key="glance_search")

view = regs[regs["category"].isin(picked or categories)]
if search.strip():
    terms = search.lower().split()
    view = view[view["name"].str.lower().apply(lambda n: all(t in n for t in terms))]

if view.empty:
    st.info("No registers match your filters.")

# ---------------------------------------------------------------- tiles, grouped by type
for category in categories:
    group = view[view["category"] == category].sort_values("name")
    if group.empty:
        continue
    st.subheader(category)
    with st.grid(3, gap="medium"):
        for _, r in group.iterrows():
            with st.container(border=True, height="stretch"):
                st.markdown(f"**{r['name']}**")
                sheets = f"{r['sheets']} sheets" if r["sheets"] > 1 else "1 sheet"
                st.caption(f"{r['folder']} · {sheets} · {r['columns']} columns")
                m1, m2 = st.columns(2)
                m1.metric("Rows", gd.compact(r["rows"]), help=f"{int(r['rows']):,} rows")
                if r["amount_label"]:
                    m2.metric(r["amount_label"], gd.compact(r["amount_sum"]))
                else:
                    m2.metric("Sheets", f"{r['sheets']}")
                if pd.notna(r["date_min"]):
                    st.caption(f":material/date_range: {fmt_date(r['date_min'], '%b %Y')} to "
                               f"{fmt_date(r['date_max'], '%b %Y')}")
                st.caption(f":material/update: File updated {fmt_date(r['file_updated'])}")

# ---------------------------------------------------------------- detail table
with st.expander("All loaded tables"):
    detail = gd.catalog_table().rename(columns={
        "table_name": "Table", "file": "Source file", "sheet_name": "Sheet", "row_count": "Rows",
        "column_count": "Columns", "file_mtime": "File updated", "loaded_at": "Loaded"})
    st.dataframe(detail, hide_index=True, width="stretch", alt="All tables loaded into the Register database")
