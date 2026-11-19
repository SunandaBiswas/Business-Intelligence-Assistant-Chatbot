from datetime import date, timedelta

import pandas as pd
import streamlit as st

import glance_data as gd
import sql_agent
import summary_data as sm
from common import check_database

ok, msg = check_database()
if not ok:
    st.error(msg, title="Database not reachable")
    st.stop()

src = sm.sources()
order = {c: i for i, c in enumerate(gd.CATEGORY_ORDER)}
options = src.assign(_o=src["category"].map(order)).sort_values(["_o", "name"])["name"].tolist()
info = src.set_index("name")


def label(name):
    row = info.loc[name]
    extra = "" if row["measure"] == "Premium" else f" · {row['measure']}"      # what the amount is, when not premium
    if pd.isna(row["date_min"]):
        return f"{name}{extra}"
    return f"{name}  ({row['date_min']:%Y}–{row['date_max']:%Y}){extra}"


# ---------------------------------------------------------------- selection (kept across reruns)
DEFAULTS = ["Collection Register 2021-23", "Collection Register 2024-2025 as of 1 April 2026"]
if "summary_selected" not in st.session_state:
    st.session_state.summary_selected = [n for n in DEFAULTS if n in options] or options[:2]
selected_names = [n for n in st.session_state.summary_selected if n in options]


@st.dialog("Select registers to compare", width="large")
def select_dialog():
    """Choose which registers appear in the comparison."""
    chosen = st.multiselect(
        "Registers", options, format_func=label, max_selections=8, key="summary_dialog_select",
        placeholder="Choose registers...",
        help="Pick up to 8 registers. Years in brackets show the dates each register covers.")
    st.caption("Tip: registers that cover different years stack into one timeline; "
               "registers that cover the same years are best compared side by side.")
    unlisted = sorted(set(gd.registers()["name"]) - set(options))
    if unlisted:
        st.caption("Not listed, because they have no date or amount column to summarise: " + ", ".join(unlisted) + ".")
    apply_col, cancel_col = st.columns(2)
    if apply_col.button("Apply", type="primary", width="stretch", disabled=not chosen,
                        key="summary_apply"):
        st.session_state.summary_selected = chosen
        st.rerun()                               # closes the pop-up and redraws the page
    if cancel_col.button("Cancel", width="stretch", key="summary_cancel"):
        st.rerun()


top_text, top_button = st.columns([4, 1], vertical_alignment="center")
top_text.caption("Amounts (premium, claims paid, targets) by year, month, week, class and customer, compared "
                 "across the registers you select. Dates come from each register's main date: credit date "
                 "for collection registers, payment date for claims, expiry date for renewal registers.")
if top_button.button("Select registers", icon=":material/checklist:", key="summary_select",
                     type="primary", width="stretch"):
    st.session_state["summary_dialog_select"] = selected_names     # pop-up starts from the current choice
    select_dialog()

if not selected_names:
    st.info("Click **Select registers** to choose what to compare.")
    st.stop()

selected = src[src["name"].isin(selected_names)].set_index("name").loc[selected_names].reset_index()

with st.container(horizontal=True):
    st.badge("Comparing", icon=":material/compare_arrows:", color="gray")
    for n in selected_names:
        st.badge(n, color="green")

measures = sorted(set(selected["measure"]))
measure_name = measures[0] if len(measures) == 1 else "Amount"      # what the figures are called on this page
if len(measures) > 1:
    st.info(f"The selected registers measure different things ({', '.join(measures)}), so a stacked chart adds "
            "unlike amounts together. Use **Side by side** to compare them.", icon=":material/info:")

# registers whose dates overlap would count the same amount twice in a stacked chart
overlaps = [(a["name"], b["name"]) for i, a in selected.iterrows() for _, b in selected.iloc[i + 1:].iterrows()
            if pd.notna(a["date_min"]) and pd.notna(b["date_min"])
            and a["date_min"] <= b["date_max"] and b["date_min"] <= a["date_max"]]
if overlaps:
    a, b = overlaps[0]
    st.info(f"Some selected registers cover overlapping dates (for example {a} and {b}), so a "
            f"stacked chart may count the same {measure_name.lower()} twice. Use **Side by side** to compare them.",
            icon=":material/info:")

# ---------------------------------------------------------------- filters (apply to every report)
cust_sources = tuple((r["table"], r["customer_col"]) for _, r in selected.iterrows() if pd.notna(r["customer_col"]))
class_sources = tuple((r["table"], r["class_col"], r["amount_col"]) for _, r in selected.iterrows()
                      if pd.notna(r["class_col"]))
customers, classes = (), ()
with st.container(border=True):
    st.markdown("**Filters**")
    fc, fk = st.columns(2)
    with fc:
        all_customers = st.checkbox("All customers", value=True, key="summary_all_customers")
        if not all_customers:
            search = st.text_input("Find customers", placeholder="Type at least 3 letters, then pick from the list",
                                   key="summary_cust_search")
            found, counts = [], {}
            if len(search.strip()) >= 3 and cust_sources:
                m = sm.find_customers(search.strip(), cust_sources)
                found, counts = m["name"].tolist(), dict(zip(m["name"], m["n"]))
            kept = st.session_state.get("summary_cust_pick", [])        # keep earlier picks while searching again
            customers = tuple(st.multiselect(
                "Customers", list(dict.fromkeys(list(kept) + found)), key="summary_cust_pick",
                format_func=lambda n: f"{n}  ({counts[n]:,} rows)" if n in counts else n,
                help="Only these customers are counted in every report below."))
    with fk:
        all_classes = st.checkbox("All classes", value=True, key="summary_all_classes")
        if not all_classes:
            class_opts = sm.class_options(class_sources)
            st.session_state["summary_class_pick"] = [c for c in st.session_state.get("summary_class_pick", [])
                                                      if c in class_opts]
            picked_classes = st.multiselect("Classes", class_opts, key="summary_class_pick",
                                            help="Only these classes are counted in every report below.")
            classes = tuple(sm.class_code(c) for c in picked_classes)
if not all_customers and not customers:
    st.info("Pick one or more customers above, or tick **All customers**.")
    st.stop()
if not all_classes and not classes:
    st.info("Pick one or more classes above, or tick **All classes**.")
    st.stop()

# ---------------------------------------------------------------- controls
REPORT_HELP = ("Year-wise, Month-wise and Weekly are period reports; "
               "Class-wise and Customer-wise are breakdowns.")
mode = st.segmented_control(
    "Selection", ["Single", "Multiple"], default="Single", required=True, key="summary_mode",
    help="Single: one report at a time. Multiple: pick several reports and see them one under another.")
if mode == "Single":
    views = [st.segmented_control("Report", sm.VIEWS, default=sm.VIEWS[0], required=True,
                                  key="summary_view", bind="query-params", help=REPORT_HELP)]
else:
    chosen_views = st.segmented_control("Reports", sm.VIEWS, selection_mode="multi",
                                        default=[sm.VIEWS[0]], key="summary_views", help=REPORT_HELP)
    views = [v for v in sm.VIEWS if v in (chosen_views or [])]       # keep a stable order
    if not views:
        st.info("Pick at least one report above.")
        st.stop()

needs_top = any(v in ("Class-wise", "Customer-wise") for v in views)
needs_period = any(v in sm.PERIOD_VIEWS for v in views)
needs_month = "Weekly" in views

c1, c2, c3, c4 = st.columns(4, vertical_alignment="bottom")
with c1:
    style = st.segmented_control("Chart", ["Stacked", "Side by side"], default="Stacked",
                                 required=True, key="summary_style", bind="query-params")
with c2:
    date_mode = st.segmented_control(
        "Dates", ["Year & month", "Date range"], default="Year & month", required=True,
        key="summary_dates", bind="query-params",
        help="Year & month: Month-wise uses the Year, Weekly uses the Year and Month; other "
             "reports cover all dates. Date range: every report is limited to the dates you pick.")
top, year, month, start, end = 10, None, None, None, None
if needs_top:
    with c3:
        top = st.segmented_control("Show top", [5, 10, 15, 20], default=10, required=True,
                                   key="summary_top")

dated = selected.dropna(subset=["date_min"])     # registers with no dates (lookup lists, yearly tables) don't count here
lo = dated["date_min"].min().date() if len(dated) else date.today()          # dates covered by the selected registers
hi = dated["date_max"].max().date() if len(dated) else date.today()

if date_mode == "Date range":
    PRESETS = ["Last 30 days", "Last 90 days", "Year to date", "Previous year", "All dates"]

    def clamp(a, b):
        a, b = max(a, lo), min(b, hi)
        return (a, b) if a <= b else (lo, hi)

    def apply_preset():
        p = st.session_state.get("summary_preset")
        if p:
            st.session_state["summary_range"] = clamp(*{
                "Last 30 days": (hi - timedelta(days=29), hi),
                "Last 90 days": (hi - timedelta(days=89), hi),
                "Year to date": (date(hi.year, 1, 1), hi),
                "Previous year": (date(hi.year - 1, 1, 1), date(hi.year - 1, 12, 31)),
                "All dates": (lo, hi),
            }[p])
            st.session_state["summary_preset"] = None      # so the same preset can be clicked again

    current = st.session_state.get("summary_range")
    if not (isinstance(current, (tuple, list)) and current and all(lo <= d <= hi for d in current)):
        st.session_state["summary_range"] = clamp(hi - timedelta(days=89), hi)

    r1, r2 = st.columns([3, 2], vertical_alignment="bottom")
    with r1:
        st.pills("Quick range", PRESETS, key="summary_preset", on_change=apply_preset,
                 help=f"Counted back from the latest date in the selected registers ({hi:%d %b %Y}).")
    with r2:
        picked = st.date_input("Date range", min_value=lo, max_value=hi, key="summary_range",
                               format="YYYY/MM/DD", help="Click a start date, then an end date.")
    if len(picked) < 2:
        st.info("Pick an end date to finish the range.")
        st.stop()
    start, end = picked
elif needs_period:
    # any year covered by the selected registers; the month is used by Weekly and the full report
    years = list(range(hi.year, lo.year - 1, -1))
    if st.session_state.get("summary_year") not in years:
        st.session_state["summary_year"] = years[0]
    st.session_state.setdefault("summary_month", sm.MONTHS[hi.month - 1])
    y1, y2, _, _ = st.columns(4, vertical_alignment="bottom")
    with y1:
        year = st.selectbox("Year", years, key="summary_year")
    with y2:
        month_name = st.selectbox("Month", sm.MONTHS, key="summary_month", disabled=not needs_month,
                                  help="Used by the Weekly report and by the full report download.")
    month = sm.MONTHS.index(month_name) + 1

range_text = f"{start:%d %b %Y} – {end:%d %b %Y}" if start else None

# ---------------------------------------------------------------- headline strip (follows the dates)
years_wide, _ = sm.compare("Year-wise", selected, start=start, end=end, classes=classes, customers=customers)
grand_total = years_wide.sum().sum() if not years_wide.empty else 0
if not grand_total:                    # registers with no years (lookup lists): total from another view instead
    for fallback in ("Class-wise", "Customer-wise"):
        other, _ = sm.compare(fallback, selected, 1000, start=start, end=end, classes=classes, customers=customers)
        if not other.empty:
            grand_total = other.sum().sum()
            break
if not grand_total:
    st.warning(f"No {measure_name.lower()} matches these filters in the selected registers and dates.")
    st.stop()
total_label = measure_name if measure_name.lower().startswith("total") else f"Total {measure_name.lower()}"
with st.grid(3, gap="medium"):
    st.metric("Registers compared", f"{len(selected_names)}", border=True, height="stretch")
    st.metric(f"{total_label} (selected)", gd.compact(grand_total), border=True,
              height="stretch",
              help=f"Sum of {measure_name.lower()} across all selected registers" + (f" for {range_text}" if range_text else "")
                   + (", for the chosen customers" if customers else "")
                   + (", for the chosen classes" if classes else "") + ".")
    if range_text:
        st.metric("Days in date range", f"{(end - start).days + 1:,}", border=True, height="stretch",
                  help=range_text)
    else:
        st.metric("Dates covered", f"{years_wide.index.min()}–{years_wide.index.max()}" if not years_wide.empty
                  else "No dates", border=True, height="stretch")


def bar_option(frame, stacked, horizontal):
    """ECharts bar option: one series per register, values shown in millions."""
    dim = frame.index.name
    data = (frame.fillna(0) / 1e6).reset_index()
    series = []
    for name in frame.columns:
        s = {"type": "bar", "name": name,
             "encode": {"x": name, "y": dim} if horizontal else {"x": dim, "y": name}}
        if stacked:
            s["stack"] = "total"
        series.append(s)
    value_axis = {"type": "value"}                        # unit (millions) is in the chart heading
    category_axis = {"type": "category"}
    if horizontal:
        category_axis.update(inverse=True, axisLabel={"width": 230, "overflow": "truncate"})
    return {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "valueFormatter": "%,.1f M"},
        "legend": {"type": "scroll", "top": 0},
        "grid": {"top": 44, "containLabel": True},
        "dataset": {"source": data},
        "xAxis": value_axis if horizontal else category_axis,
        "yAxis": category_axis if horizontal else value_axis,
        "series": series,
    }


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WHAT = {"Year-wise": "year", "Month-wise": "month", "Weekly": "week",
        "Class-wise": "class", "Customer-wise": "customer"}
NOUN = {"Year-wise": "years", "Month-wise": "months", "Weekly": "weeks", "Class-wise": "classes",
        "Customer-wise": "customers"}
full_report_shown = False


def item_filter(view, items):
    """Each report's own selector: a checkbox ('All ...', on by default) and a dropdown to show only some.
    Returns the picked items, or None for all."""
    k_all, k_pick = f"summary_all_{view}", f"summary_items_{view}"
    a, b = st.columns([1, 3], vertical_alignment="center")
    if a.checkbox(f"All {NOUN[view]}", value=True, key=k_all):
        return None
    st.session_state[k_pick] = [v for v in st.session_state.get(k_pick, []) if v in items]
    picked = b.multiselect(f"Show only these {NOUN[view]}", items, key=k_pick,
                           help="Untick 'All' to choose specific items. For a customer that isn't listed, "
                                "use the Customers filter at the top of the page." if view == "Customer-wise" else None)
    return picked or None


# ---------------------------------------------------------------- one section per chosen report
for view in views:
    breakdown = view in ("Class-wise", "Customer-wise")
    wide_all, skipped = sm.compare(view, selected, 1000 if breakdown else top, year=year, month=month,
                                   start=start, end=end, classes=classes, customers=customers)
    if skipped:
        st.caption(f"{view}: not included: " + ", ".join(
            s if "(" in s else f"{s} (no {view.split('-')[0].lower()} column)" for s in skipped))
    if wide_all.empty:
        st.warning(f"None of the selected registers have a {view} breakdown.")
        continue
    pick = item_filter(view, list(wide_all.index))
    if pick:
        wide = wide_all.loc[[i for i in wide_all.index if i in pick]]
    else:
        wide = wide_all.head(top) if breakdown else wide_all

    horizontal = view in ("Class-wise", "Customer-wise")
    height = max(340, 34 * len(wide) + 120) if horizontal else 420
    if range_text:
        scope, slug_scope = range_text, f"{start:%Y%m%d}_{end:%Y%m%d}"
    else:
        scope = {"Month-wise": f"{year}", "Weekly": f"{sm.MONTHS[(month or 1) - 1]} {year}"}.get(view, "")
        slug_scope = scope.replace(" ", "_")
    title = f"{measure_name} by {WHAT[view]}" + (f" · {scope}" if scope else "")
    slug = "_".join([view.lower().replace("-", "_")] + ([slug_scope] if slug_scope else []))

    if view in sm.PERIOD_VIEWS and wide.isna().all().all():
        st.info(f"No {measure_name.lower()} is recorded for {scope} in the selected registers. "
                "Try other dates, or add a register that covers them.", icon=":material/info:")
    if view == "Weekly" and len(wide) > 120:
        st.caption(f"{len(wide)} {WHAT[view]}s fall in this range, so the chart is crowded. "
                   "A shorter date range reads better.")

    with st.container(border=True):
        st.subheader(f"{title} (millions)")
        st.echarts_chart(bar_option(wide, style == "Stacked", horizontal), height=height,
                         alt=f"{title} for {len(wide.columns)} registers, "
                             f"{'stacked' if style == 'Stacked' else 'side by side'}")

    table = wide.fillna(0)                      # a register with no data for a period shows 0, not "None"
    table["Total"] = table.sum(axis=1)
    with st.container(border=True):
        head, buttons = st.columns([3, 3], vertical_alignment="center")
        head.subheader(f"{title}: data")
        with buttons:
            with st.container(horizontal=True, horizontal_alignment="right"):
                st.download_button(
                    "Download this report", data=sql_agent.to_excel_bytes(table.reset_index(), sheet_name=view),
                    file_name=f"summary_{slug}.xlsx", icon=":material/download:", mime=XLSX,
                    key=f"summary_download_{slug}")
                if view in sm.PERIOD_VIEWS and not full_report_shown:   # one full report per page
                    full_report_shown = True
                    if range_text:
                        full_name = f"summary_full_report_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
                        full_help = f"One workbook with Year-wise, Months and Weeks for {range_text}."
                    else:
                        mon = sm.MONTHS[month - 1]
                        full_name = f"summary_full_report_{mon}_{year}.xlsx"
                        full_help = (f"One workbook with Year-wise, Months of {year}, and the Weeks "
                                     f"of {mon} {year}.")
                    st.download_button(
                        "Download full period report", icon=":material/download:", mime=XLSX,
                        data=sm.period_report_bytes(selected, year, month, start, end, classes, customers),
                        file_name=full_name, key="summary_download_full", help=full_help)
        st.dataframe(
            table, width="stretch", alt=f"{title} for the selected registers",
            column_config={c: st.column_config.NumberColumn(format="%,.0f") for c in table.columns})
