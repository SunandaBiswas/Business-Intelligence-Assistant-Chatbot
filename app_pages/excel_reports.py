import re
from datetime import date

import pandas as pd
import streamlit as st

import excel_pivot as xp
import glance_data as gd
import report_data as rd
import report_style as rs
from common import check_database

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ok, msg = check_database()
if not ok:
    st.error(msg, title="Database not reachable")
    st.stop()

st.caption("Excel reports in the format departments receive, and a pivot generator for anything else. "
           "Every report can be delivered as plain values, with formulas for the totals, or with live "
           "formulas over a data sheet.")
section = st.segmented_control("Report type", ["Department report", "Pivot generator"],
                               default="Department report", required=True, key="xl_section",
                               bind="query-params")


def style_controls(prefix):
    """Palette, layout options and a live preview of the Excel look. Returns the style dict."""
    with st.container(border=True):
        st.markdown("**Report style**")
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            name = st.selectbox("Colour palette", list(rs.PALETTES) + [rs.CUSTOM], key=f"{prefix}_palette",
                                help="Executive-ready colour sets. Choose Custom colour to pick your own.")
            if name == rs.CUSTOM:
                base = st.color_picker("Base colour", "#0A5A2F", key=f"{prefix}_color",
                                       help="The header colour. The title bar, banding, totals and borders "
                                            "are matched to it automatically.")
                palette = rs.palette_from_base(base)
            else:
                palette = rs.PALETTES[name]
            t1, t2 = st.columns(2)
            banding = t1.toggle("Banded rows", value=True, key=f"{prefix}_band")
            scale = t2.toggle("Colour scale on values", value=False, key=f"{prefix}_scale",
                              help="Shades the numbers from light to dark, so the biggest stand out.")
            t3, t4 = st.columns(2)
            grid = t3.toggle("Show gridlines", value=False, key=f"{prefix}_grid")
            note = t4.toggle("Add source note", value=True, key=f"{prefix}_note",
                             help="A small line under each table: where the data came from and the date.")
        with right:
            st.image(rs.preview_png(palette), width="stretch", alt="Preview of the report colours")
    return {"palette": palette, "banding": banding, "colour_scale": scale, "gridlines": grid, "note": note}


def checkbox_dropdown(label, options, default, key, help=None):
    """A dropdown that opens a list of tick boxes. Returns the ticked options, in list order."""
    box = {o: f"{key}__{o}" for o in options}
    ticked = [o for o in options if st.session_state.get(box[o], o in default)]
    st.markdown(label)
    summary = "(nothing ticked)" if not ticked else ticked[0] if len(ticked) == 1 else f"{ticked[0]} +{len(ticked) - 1} more"
    with st.popover(summary, width="stretch", icon=":material/checklist:", help=help):
        st.caption(f"Tick the {label.lower()} you want.")
        with st.container(height=min(330, 40 * len(options) + 10) if len(options) > 7 else "content"):
            for o in options:
                st.checkbox(o, value=o in default, key=box[o])
    return [o for o in options if st.session_state.get(box[o], o in default)]


def generate_gate(key, signature):
    """A Generate button. The report is built and previewed only after it is clicked, and it goes away
    again if any option changes afterwards, so what you see is always what you download."""
    sig_key = f"xl_sig_{key}"
    if st.button("Generate report", icon=":material/play_arrow:", type="primary", key=f"xl_gen_{key}"):
        st.session_state[sig_key] = signature
    done = st.session_state.get(sig_key)
    if done is None:
        st.info("Set your options above, then click **Generate report** to see it here before downloading.")
        st.stop()
    if done != signature:
        st.info("Your settings changed. Click **Generate report** to refresh the preview.")
        st.stop()


def show_report(blocks, mode, file_stem, style):
    """Preview each table as it will look in Excel, then the download button."""
    for b in blocks:
        with st.container(border=True):
            st.markdown(f"**{b['title']}**")
            frame = xp.preview_frame(b)
            frame.columns = [str(c) for c in frame.columns]
            fmt = "%,.2f" if b["agg"] == "Average" else "%,.0f"
            st.dataframe(frame, width="stretch", alt=b["title"],
                         column_config={c: st.column_config.NumberColumn(format=fmt) for c in frame.columns})
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file_stem).strip("_") or "report"
    st.download_button("Download Excel report", data=xp.build_workbook(blocks, mode, style=style),
                       file_name=f"{safe}.xlsx", icon=":material/download:", type="primary", mime=XLSX,
                       key="xl_download", help=f"Output: {mode}.")


# =================================================================== department report
if section == "Department report":
    all_regs = gd.registers()
    order = {c: i for i, c in enumerate(gd.CATEGORY_ORDER)}
    reg_names = all_regs.assign(_o=all_regs["category"].map(order)).sort_values(["_o", "name"])["name"].tolist()
    reg_category = dict(zip(all_regs["name"], all_regs["category"]))
    reg_tables = dict(zip(all_regs["name"], all_regs["tables"]))
    picked_regs = st.multiselect(
        "SELECT REGISTER", reg_names, key="xl_dept_regs",
        default=[n for n in ("Collection Register", "Claim Register") if n in reg_names],
        format_func=lambda n: f"{reg_category[n]} · {n}",
        help="Every register is listed. Each one you pick becomes its own table in the report: premium "
             "registers give premium by class and year, the claim register gives paid claims, and so on.")
    if not picked_regs:
        st.info("Pick at least one register.")
        st.stop()

    # ---- how the file looks: shown straight away, before any customer is picked
    mode = st.segmented_control("Excel output", xp.MODES, default=xp.MODES[0], required=True, key="xl_mode",
                                help=xp.MODE_HELP)
    style = style_controls("xl_dept")

    def plan_for(name):
        """The sheet to read for a register and which columns hold its date / class / customer / amount."""
        fallback = None
        for table in reg_tables[name]:                     # biggest sheet first
            ro = rd.roles(table)
            if ro["date_col"] and ro["amount_col"]:
                return {"name": name, "table": table, **ro}
            if ro["date_col"] and fallback is None:
                fallback = {"name": name, "table": table, **ro}
        return fallback                                     # None when no sheet has a date column

    plans = [p for p in (plan_for(n) for n in picked_regs) if p]
    for n in picked_regs:
        if not any(p["name"] == n for p in plans):
            st.caption(f"{n}: left out, because it has no date column to group by year.")
    if not plans:
        st.stop()

    # ---- customers: search, then pick (or include everyone)
    everyone = st.checkbox("All customers (no customer filter)", value=False, key="xl_dept_all")
    chosen = []
    if not everyone:
        search = st.text_input("Find customer", placeholder="Type at least 3 letters of the name, e.g. BIMAFY",
                               key="xl_search")
        if len(search.strip()) < 3:
            st.info("Type part of a customer name to start, or tick **All customers**.")
            st.stop()
        sources = tuple((p["table"], p["customer_col"]) for p in plans if p["customer_col"])
        if not sources:
            st.warning("None of the selected registers has a customer column. Tick **All customers**.")
            st.stop()
        matches = rd.find_customers(search.strip(), sources)
        if matches.empty:
            st.warning("No customer name matches that text.")
            st.stop()
        counts = dict(zip(matches["name"], matches["n"]))
        chosen = st.multiselect("Customers to include", matches["name"].tolist(), key="xl_customers",
                                format_func=lambda n: f"{n}  ({counts[n]:,} rows)",
                                help="Pick more than one to combine spellings of the same customer.")
        if not chosen:
            st.info("Pick one or more customers from the matches above.")
            st.stop()
        for p in plans:
            if not p["customer_col"]:
                st.caption(f"{p['name']}: left out, because it has no customer column.")
        plans = [p for p in plans if p["customer_col"]]

    title_name = st.text_input("Name shown in the report titles", value="All customers" if everyone else chosen[0],
                               key=f"xl_title_{'all' if everyone else chosen[0]}")

    def suffix(p):
        label = p["amount_label"]
        if label == "Premium":
            return "Premium Collection Data"
        if label == "Amount paid":
            return "Year wise Paid Claim Amount"
        return f"Year wise {label}" if label else "Year wise Record Count"

    def spec(p):
        row_field = ("text", p["class_col"]) if p["class_col"] else ("all", None)
        return (p["table"], p["date_col"], row_field, ("year", None), p["amount_col"])

    def fetch(p):
        flt = (("in", p["customer_col"], tuple(chosen)),) if chosen else ()
        agg = "Sum" if p["amount_col"] else "Count"
        return rd.aggregate(*spec(p), agg, None, flt), flt, agg

    results = [(p, *fetch(p)) for p in plans]
    years = sorted({y for _, r, _, _ in results for y in r["wide"].columns if y != rd.BLANK})
    if not years:
        st.warning("Nothing was found for these customers in the selected registers.")
        st.stop()
    picked_years = st.multiselect("Years to include", years, default=years)
    if not picked_years:
        st.info("Pick at least one year.")
        st.stop()

    generate_gate("dept", repr((picked_regs, everyone, chosen, title_name, mode, picked_years, style)))

    effective_mode = mode
    blocks = []
    source_note = (f"Source: {', '.join(p['name'] for p in plans)} · Generated {date.today():%d %b %Y}"
                   if style["note"] else None)
    suffix_count = {}
    for p in plans:
        suffix_count[suffix(p)] = suffix_count.get(suffix(p), 0) + 1
    for i, (p, res, flt, agg) in enumerate(results, start=1):
        label = suffix(p)
        wide = res["wide"].reindex(columns=[y for y in picked_years if y in res["wide"].columns])
        wide = wide.loc[(wide != 0).any(axis=1)] if not wide.empty else wide
        if wide.empty or wide.shape[1] == 0:
            st.caption(f"{p['name']}: nothing found in the chosen years.")
            continue
        data = None
        if mode == "Full formulas":
            data, truncated = rd.raw_rows(*spec(p), None, flt)
            data = data[data["col_key"].isin(picked_years) & data["row_key"].isin(wide.index)]
            if truncated:
                effective_mode = "Totals as formulas"
        title = f"{title_name}_ {label}" + (f" ({p['name']})" if suffix_count[label] > 1 else "")
        blocks.append(xp.make_block(title, "Class Code" if p["class_col"] else "Records", wide, agg,
                                    p["amount_label"] or "Records", data=data,
                                    data_sheet=f"Data_{i}_{re.sub(r'[^A-Za-z0-9]+', '', p['name'])[:18]}",
                                    note=source_note))
    if not blocks:
        st.stop()
    if effective_mode != mode:
        st.warning(f"A register has more than {rd.MAX_RAW_ROWS:,} matching rows, too many for a data sheet. "
                   "The file uses formulas for the totals only.")
    show_report(blocks, effective_mode, f"{title_name}_report", style)

# =================================================================== pivot generator
else:
    regs = gd.registers()
    order = {c: i for i, c in enumerate(gd.CATEGORY_ORDER)}
    names = regs.assign(_o=regs["category"].map(order)).sort_values(["_o", "name"])["name"].tolist()
    category_of = dict(zip(regs["name"], regs["category"]))
    r1, r2 = st.columns([3, 2])
    reg_name = r1.selectbox("SELECT REGISTER", names, key="xl_pv_reg", format_func=lambda n: f"{category_of[n]} · {n}",
                            index=names.index("Collection Register") if "Collection Register" in names else 0)
    R = regs.set_index("name").loc[reg_name]
    tables = list(R["tables"])
    table = tables[0] if len(tables) == 1 else r2.selectbox("Sheet", tables, key=f"xl_pv_sheet_{reg_name}")
    cols = rd.table_columns()[table]
    ro = rd.roles(table)
    date_col = ro["date_col"]
    non_date = [c for c, t in cols if t not in rd.DATE_TYPES]

    fields = {}
    if date_col:
        fields[f"Year of {date_col}"] = ("year", None)
        fields[f"Month of {date_col}"] = ("month", None)
    fields.update({c: ("text", c) for c in non_date})
    field_names = list(fields)
    value_names = ["Count of rows"] + [c for c in non_date if rd.amount_like(c)] + \
                  [c for c in non_date if not rd.amount_like(c)]

    default_row = ro["class_col"] if ro["class_col"] in field_names else field_names[0]
    default_col = f"Year of {date_col}" if date_col else None
    default_val = ro["amount_col"] if ro["amount_col"] in value_names else "Count of rows"
    f1, f2, f3 = st.columns(3)
    with f1:
        rows_sel = checkbox_dropdown(
            "Rows", field_names, [default_row], f"xl_pv_rows_{table}",
            help="Tick one or more fields. With several ticked, each row is a combination, such as GHI | B.")
    with f2:
        cols_sel = checkbox_dropdown(
            "Columns", field_names, [default_col] if default_col else [], f"xl_pv_cols_{table}",
            help="Tick none, one or more fields. With several ticked, each column is a combination, such as 2025 | B.")
    with f3:
        vals_sel = checkbox_dropdown(
            "Values", value_names, [default_val], f"xl_pv_vals_{table}",
            help="Tick one or more. Each ticked value gets its own table in the report.")
    count_only = vals_sel == ["Count of rows"]
    agg = st.segmented_control("Calculation", rd.AGGS, default="Sum", required=True,
                               key=f"xl_pv_agg_{table}", disabled=count_only,
                               help="Sum, Count, Average, Min or Max of the ticked values.")
    if count_only:
        agg = "Count"
    if not rows_sel:
        st.info("Tick at least one field under **Rows**.")
        st.stop()
    if not vals_sel:
        st.info("Tick at least one item under **Values**.")
        st.stop()
    if set(rows_sel) & set(cols_sel):
        st.warning("A field can't be in both Rows and Columns. Untick it in one of them.")
        st.stop()

    # ---- filters
    date_range, filters, need_customers, need_pick = None, [], False, False

    # ---- which items of each ticked field: "Select all", or pick specific ones (class codes, customers, years...)
    with st.container(border=True):
        st.markdown("**Choose items**")
        st.caption("For each ticked field, use all of its items, or untick **Select all** and pick the ones you want.")
        for where_, fname in [("Rows", f) for f in rows_sel] + [("Columns", f) for f in cols_sel]:
            kind, col = fields[fname]
            k = f"{table}_{where_}_{fname}"
            c1, c2 = st.columns([1, 3], vertical_alignment="top")
            if c1.checkbox(f"Select all {fname}", value=True, key=f"xl_pv_all_{k}"):
                continue
            with c2:
                if kind == "year":
                    yv = rd.year_values(table, date_col)
                    counts = {int(y): int(n) for y, n in zip(yv["value"], yv["n"])}
                    picked_items = st.multiselect(f"{fname}: select items", list(counts), key=f"xl_pv_pick_{k}",
                                                  format_func=lambda y: f"{y}  ({counts[y]:,} rows)")
                    if picked_items:
                        filters.append(("year", "", tuple(picked_items)))
                elif kind == "month":
                    picked_items = st.multiselect(f"{fname}: select items", rd.MONTHS, key=f"xl_pv_pick_{k}")
                    if picked_items:
                        filters.append(("month", "", tuple(rd.MONTHS.index(m) + 1 for m in picked_items)))
                else:
                    total = rd.cardinality(table, col)
                    counts = {}
                    if total <= 300:                                   # short list: show everything
                        dv = rd.distinct_values(table, col, 300)
                        counts = dict(zip(dv["value"], dv["n"]))
                        options = list(counts)
                    else:                                              # long list (customers, ...): search first
                        text = st.text_input(f"Find {fname}", placeholder="Type at least 3 letters",
                                             key=f"xl_pv_q_{k}", help=f"{fname} has {total:,} different values.")
                        if len(text.strip()) >= 3:
                            m = rd.find_values(table, col, text)
                            counts = dict(zip(m["value"], m["n"]))
                        kept = st.session_state.get(f"xl_pv_pick_{k}", [])      # keep earlier picks while searching again
                        options = list(dict.fromkeys(list(kept) + list(counts)))
                    picked_items = st.multiselect(f"{fname}: select items", options, key=f"xl_pv_pick_{k}",
                                                  format_func=lambda v: f"{v}  ({counts[v]:,})" if v in counts else v)
                    if picked_items:
                        filters.append(("in", col, tuple(picked_items)))
                if not picked_items:
                    need_pick = True

    with st.container(border=True):                      # always visible, not hidden in the Filters box
        st.markdown("**Customers**")
        if ro["customer_col"]:
            if not st.checkbox("All customers", value=True, key=f"xl_pv_allcust_{table}"):
                text = st.text_input("Find customers", placeholder="Type at least 3 letters, then pick from the list",
                                     key=f"xl_pv_custq_{table}")
                found, counts = [], {}
                if len(text.strip()) >= 3:
                    m = rd.find_customers(text.strip(), ((table, ro["customer_col"]),))
                    found, counts = m["name"].tolist(), dict(zip(m["name"], m["n"]))
                kept = st.session_state.get(f"xl_pv_custpick_{table}", [])      # keep earlier picks while searching again
                picked_names = st.multiselect(
                    "Select customers", list(dict.fromkeys(list(kept) + found)), key=f"xl_pv_custpick_{table}",
                    format_func=lambda n: f"{n}  ({counts[n]:,} rows)" if n in counts else n,
                    help="Only these customers are included in the pivot. Pick as many as you need.")
                if picked_names:
                    filters.append(("in", ro["customer_col"], tuple(picked_names)))
                else:
                    need_customers = True
        else:
            st.caption("This register has no customer column, so every row is included.")
    with st.expander("Filters", icon=":material/filter_alt:"):
        if date_col:
            lo = R["date_min"].date() if pd.notna(R["date_min"]) else date(2000, 1, 1)
            hi = R["date_max"].date() if pd.notna(R["date_max"]) else date.today()
            if st.checkbox(f"Limit to a date range ({date_col})", key=f"xl_pv_usedate_{table}"):
                picked = st.date_input("Date range", value=(lo, hi), min_value=date(2000, 1, 1),
                                       max_value=date(2099, 12, 31), key=f"xl_pv_dates_{table}",
                                       format="YYYY/MM/DD")
                if len(picked) == 2:
                    date_range = tuple(picked)
                else:
                    st.caption("Pick an end date to finish the range.")
        for i in (1, 2):
            fc1, fc2 = st.columns([2, 4], vertical_alignment="bottom")
            col_f = fc1.selectbox(f"Filter {i}: column", ["(none)"] + non_date, key=f"xl_pv_f{i}c_{table}")
            if col_f != "(none)":
                dv = rd.distinct_values(table, col_f)
                shown = dict(zip(dv["value"], dv["n"]))
                chosen_vals = fc2.multiselect(f"Keep only these {col_f} values", list(shown),
                                              key=f"xl_pv_f{i}v_{table}_{col_f}",
                                              format_func=lambda v: f"{v}  ({shown[v]:,})",
                                              help="Shows the 300 most common values.")
                if chosen_vals:
                    filters.append(("in", col_f, tuple(chosen_vals)))

    # ---- output options
    row_label, col_label = " | ".join(rows_sel), " | ".join(cols_sel)
    multi = len(vals_sel) > 1

    def measure(v):
        return "Count of rows" if v == "Count of rows" else f"{agg} of {v}"

    by_text = row_label + (f" and {col_label}" if cols_sel else "")
    default_title = f"By {by_text}" if multi else f"{measure(vals_sel[0])} by {by_text}"
    title = st.text_input("Report title", value=default_title,
                          key=f"xl_pv_title_{table}_{'+'.join(rows_sel)}_{'+'.join(cols_sel)}_{'+'.join(vals_sel)}_{agg}",
                          help="With several values ticked, each table's title adds the value's name." if multi else None)
    o1, o2, o3 = st.columns([3, 2, 2], vertical_alignment="bottom")
    mode = o1.segmented_control("Excel output", xp.MODES, default=xp.MODES[0], required=True,
                                key="xl_pv_mode", help=xp.MODE_HELP)
    sort_rows = o2.segmented_control("Sort rows by", ["Label", "Total (high to low)"], default="Label",
                                     required=True, key="xl_pv_sort")
    show_totals = o3.toggle("Grand totals", value=True, key="xl_pv_totals")
    include_data = False
    if mode != "Full formulas":
        include_data = st.checkbox("Also include the underlying rows as a data sheet", key="xl_pv_data",
                                   help=f"Up to {rd.MAX_RAW_ROWS:,} rows, for your own checking or pivoting.")

    style = style_controls("xl_pv")                      # the design and colour palette section, always shown

    if need_customers:
        st.info("Pick one or more customers in the Customers section above, or tick **All customers**.")
        st.stop()
    if need_pick:
        st.info("Pick at least one item for each field in **Choose items** where **Select all** is unticked.")
        st.stop()
    generate_gate("pv", repr((table, rows_sel, cols_sel, vals_sel, agg, tuple(filters), date_range, title, mode,
                              sort_rows, show_totals, include_data, style)))

    # ---- build: one table per ticked value
    def combine(sel):
        if not sel:
            return None
        return fields[sel[0]] if len(sel) == 1 else ("combo", tuple(fields[s] for s in sel))

    row_field, col_field = combine(rows_sel), combine(cols_sel)
    blocks, effective_mode, cut = [], mode, False
    for i, v in enumerate(vals_sel, start=1):
        count_rows = v == "Count of rows"
        agg_v = "Count" if count_rows else agg
        value_col = None if count_rows else v
        try:
            res = rd.aggregate(table, date_col, row_field, col_field, value_col, agg_v, date_range,
                               tuple(filters), sort_rows)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        if res["wide"].empty:
            st.caption(f"{measure(v)}: no rows match these choices.")
            continue
        data = None
        if mode == "Full formulas" or include_data:
            data, truncated = rd.raw_rows(table, date_col, row_field, col_field, value_col, date_range,
                                          tuple(filters))
            if truncated and mode == "Full formulas":
                cut = True
            elif truncated:
                st.caption(f"The data sheet for {measure(v)} holds the first {rd.MAX_RAW_ROWS:,} matching rows.")
        blocks.append(xp.make_block(
            f"{title} · {measure(v)}" if multi else title, row_label, res["wide"], agg_v, measure(v),
            res["row_tot"], res["col_tot"], res["grand"], show_totals=show_totals,
            has_cols=col_field is not None, data=data, data_sheet=f"Data_{i}" if multi else "Data",
            include_data=include_data,
            note=(f"Source: {reg_name} · Generated {date.today():%d %b %Y}" if style["note"] else None)))
    if not blocks:
        st.warning("No rows match these choices.")
        st.stop()
    if cut:
        effective_mode = "Totals as formulas"
        for b in blocks:
            b["data"] = None
        st.warning(f"More than {rd.MAX_RAW_ROWS:,} rows match, too many for a data sheet. The file uses "
                   "formulas for the totals only. Add a filter to get full formulas.")
    show_report(blocks, effective_mode, title, style)
