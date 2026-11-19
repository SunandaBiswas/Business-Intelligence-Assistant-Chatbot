"""
Data layer for the Summary page: premium per register broken down by year, month, week,
class or customer, combined side by side so several registers can be compared.

A register is usable when its biggest premium sheet has a date column and a premium column;
class and customer columns are optional (a register without one is skipped for that view).
Everything here is a small GROUP BY query, cached for 30 minutes.

Two ways to choose the dates
  * Year & month : Month-wise uses one year; Weekly uses one month of one year.
  * Date range   : start..end (inclusive) limits every report; the period reports then list every
                   month / week that falls inside the range.

Optional filters (every report): specific customers and/or specific classes.

Period definition
  Weekly  : Week 1 = days 1-7, Week 2 = 8-14, Week 3 = 15-21, Week 4 = 22-28, Week 5 = 29-end
"""
import calendar
import io
import re
from datetime import date

import pandas as pd
import streamlit as st

import glance_data as gd
from common import shared_engine

_CLASS_RE = re.compile(r"^class(_?code)?(_ms)?$|^class_code", re.I)
_CUSTOMER_RE = re.compile(r"customer|insured_?name|^name$", re.I)
_DATE_OK = "BETWEEN '2000-01-01' AND '2100-01-01'"      # ignore junk dates like 1900-01-01
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PERIOD_VIEWS = ("Month-wise", "Weekly")
VIEWS = ("Year-wise", "Month-wise", "Weekly", "Class-wise", "Customer-wise")
TOP_CUSTOMER_ROWS = 200                                  # per register, before combining
_KIND = {"Month-wise": "month", "Weekly": "week"}


def _q(sql, params=()):
    with shared_engine().connect() as conn:
        res = conn.exec_driver_sql(sql, tuple(params))
        return pd.DataFrame([tuple(r) for r in res.fetchall()], columns=list(res.keys()))


def _lit(d):
    """A date as an unambiguous SQL literal (YYYYMMDD)."""
    return "'" + d.strftime("%Y%m%d") + "'"


def _range_sql(date_col, start, end):
    """WHERE condition for an inclusive date range; with no range, just drop junk dates."""
    if start is None or end is None:
        return f"[{date_col}] {_DATE_OK}"
    return f"[{date_col}] >= {_lit(start)} AND [{date_col}] < DATEADD(day, 1, {_lit(end)})"


def _flt_sql(flt):
    """Conditions + parameters for the customer / class filters: flt = (("in", column, (values...)), ...)."""
    conds, params = [], []
    for _, col, values in flt:
        marks = ",".join("?" * len(values))
        conds.append(f"UPPER(LTRIM(RTRIM(CAST([{col}] AS nvarchar(200))))) IN ({marks})")
        params += [str(v).strip().upper() for v in values]
    return conds, params


def _where(first, flt):
    conds, params = _flt_sql(flt)
    return " AND ".join([first] + conds), params


@st.cache_data(ttl="30m", show_spinner="Reading register columns...")
def sources():
    """One row per usable register: which table/columns to read. Every register with a date column and an
    amount column is included (premium, amount paid, target, ...); `measure` says what the amount is."""
    regs = gd.registers()
    cols = _q("SELECT TABLE_NAME AS t, COLUMN_NAME AS c, DATA_TYPE AS d FROM INFORMATION_SCHEMA.COLUMNS "
              "WHERE TABLE_SCHEMA = 'dbo' ORDER BY TABLE_NAME, ORDINAL_POSITION")
    colmap = {t: list(zip(g["c"], g["d"].str.lower())) for t, g in cols.groupby("t")}
    plain = {"premium", "netpremium", "creditnet", "amountpaid", "target", "collection", "total"}
    year_re = re.compile(r"^year(_\d+)?$", re.I)

    def entry(r, table, cs):
        label, amount_col, _ = gd._pick_amount_col(cs)
        return {
            "name": r["name"], "category": r["category"], "table": table,
            "measure": label or "Records",                  # no amount column: count the records
            "date_col": gd._pick_date_col(cs), "amount_col": amount_col,
            "year_col": next((n for n, _ in cs if year_re.match(n)), None),
            "class_col": next((n for n, _ in cs if _CLASS_RE.search(n)), None),
            "customer_col": next((n for n, _ in cs if _CUSTOMER_RE.search(n)), None),
            "rows": int(r["rows"]), "date_min": r["date_min"], "date_max": r["date_max"],
        }

    out = []
    for _, r in regs.iterrows():
        entries = [entry(r, t, colmap.get(t, [])) for t in r["tables"]]      # biggest sheet first
        dated = [e for e in entries if e["date_col"] and e["amount_col"]]
        if dated:
            # prefer the sheet whose amount column is the plain one ("Target", not "Target_2024")
            out.append(next((e for e in dated if e["amount_col"].lower().replace("_", "") in plain), dated[0]))
            continue
        # no date + amount sheet (lookup lists, small yearly tables): use whatever the register can be grouped by
        usable = [e for e in entries if e["date_col"] or e["year_col"] or e["class_col"] or e["customer_col"]]
        if usable:
            best = next((e for e in usable if e["date_col"] or e["year_col"]), usable[0])
            out.append(best)
    return pd.DataFrame(out)


@st.cache_data(ttl="1h", show_spinner=False)
def class_names():
    """{'MAR': 'Marine', ...} from the Name lookup sheet."""
    df = _q("SELECT Class_Code, MAX(LTRIM(RTRIM(Class_Name))) AS Class_Name "
            "FROM dbo.PBI_Name__Class GROUP BY Class_Code")
    return {str(c).strip().upper(): n for c, n in zip(df["Class_Code"], df["Class_Name"]) if n}


def _none(v):
    """None for missing values (None / NaN), so a register without a date or amount column is easy to test."""
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def _amount(col):
    """The amount to add up. A register with no amount column counts its records instead (1 per row)."""
    col = _none(col)
    return "1" if col is None else f"TRY_CAST([{col}] AS float)"


@st.cache_data(ttl="30m", show_spinner=False)
def by_year(table, date_col, amount_col, start=None, end=None, flt=(), year_col=None):
    date_col, year_col = _none(date_col), _none(year_col)
    if date_col is None:                                 # no dates: use the register's own Year column
        year = f"TRY_CAST([{year_col}] AS int)"
        where, params = _where(f"{year} IS NOT NULL", flt)
        df = _q(f"SELECT {year} AS k, SUM({_amount(amount_col)}) AS premium "
                f"FROM dbo.[{table}] WHERE {where} GROUP BY {year}", params)
    else:
        where, params = _where(_range_sql(date_col, start, end), flt)
        df = _q(f"SELECT YEAR([{date_col}]) AS k, SUM({_amount(amount_col)}) AS premium "
                f"FROM dbo.[{table}] WHERE {where} GROUP BY YEAR([{date_col}])", params)
    df["k"] = df["k"].astype(int).astype(str)
    return df


@st.cache_data(ttl="30m", show_spinner=False)
def by_period(table, date_col, amount_col, kind, year, month=None, flt=()):
    """Premium per month (of `year`) or per week (of `month` in `year`).
    Returns k = 1..12 / 1..5. year and month are ints, so they are safe to put in the SQL."""
    year = int(year)
    if kind == "month":
        start, end = f"{year}-01-01", f"{year + 1}-01-01"
        key = f"MONTH([{date_col}])"
    else:
        month = int(month)
        start = f"{year}-{month:02d}-01"
        end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
        key = f"(DAY([{date_col}]) - 1) / 7 + 1"
    where, params = _where(f"[{date_col}] >= '{start}' AND [{date_col}] < '{end}'", flt)
    return _q(f"SELECT {key} AS k, SUM({_amount(amount_col)}) AS premium FROM dbo.[{table}] "
              f"WHERE {where} GROUP BY {key}", params)


@st.cache_data(ttl="30m", show_spinner=False)
def by_bucket(table, date_col, amount_col, kind, start, end, flt=()):
    """Premium per calendar month / week-of-month inside start..end.
    Returns k = year*10000 + month*100 + bucket (bucket is 0 for months)."""
    d = f"[{date_col}]"
    bucket = {"month": None, "week": f"(DAY({d}) - 1) / 7 + 1"}[kind]
    group = f"YEAR({d}), MONTH({d})" + (f", {bucket}" if bucket else "")
    where, params = _where(_range_sql(date_col, start, end), flt)
    df = _q(f"SELECT YEAR({d}) AS y, MONTH({d}) AS m, {bucket or '0'} AS b, "
            f"SUM({_amount(amount_col)}) AS premium FROM dbo.[{table}] "
            f"WHERE {where} GROUP BY {group}", params)
    df["k"] = df["y"].astype(int) * 10000 + df["m"].astype(int) * 100 + df["b"].astype(int)
    return df[["k", "premium"]]


@st.cache_data(ttl="30m", show_spinner=False)
def by_class(table, class_col, amount_col, date_col=None, start=None, end=None, flt=()):
    key = f"UPPER(LTRIM(RTRIM(CAST([{class_col}] AS nvarchar(100)))))"
    first = f"[{class_col}] IS NOT NULL"
    if start is not None and end is not None:
        first += f" AND {_range_sql(date_col, start, end)}"
    where, params = _where(first, flt)
    df = _q(f"SELECT {key} AS k, SUM({_amount(amount_col)}) AS premium FROM dbo.[{table}] "
            f"WHERE {where} GROUP BY {key}", params)
    names = class_names()
    df["k"] = df["k"].map(lambda c: f"{c} – {names[c]}" if c in names else c)
    return df[df["k"].astype(str).str.strip() != ""]


@st.cache_data(ttl="30m", show_spinner=False)
def by_customer(table, customer_col, amount_col, date_col=None, start=None, end=None, flt=()):
    key = f"UPPER(LTRIM(RTRIM(CAST([{customer_col}] AS nvarchar(200)))))"
    first = f"[{customer_col}] IS NOT NULL"
    if start is not None and end is not None:
        first += f" AND {_range_sql(date_col, start, end)}"
    where, params = _where(first, flt)
    return _q(f"SELECT TOP {TOP_CUSTOMER_ROWS} {key} AS k, SUM({_amount(amount_col)}) AS premium "
              f"FROM dbo.[{table}] WHERE {where} "
              f"GROUP BY {key} ORDER BY SUM({_amount(amount_col)}) DESC", params)


# ------------------------------------------------------------------ filter pick-lists
@st.cache_data(ttl="10m", show_spinner=False)
def find_customers(text, sources_):
    """Customer names containing `text` (with row counts). sources_ = ((table, customer_col), ...)"""
    pattern = "%" + re.sub(r"([\\%_\[])", r"\\\1", text.strip()) + "%"
    frames = []
    for table, col in sources_:
        key = f"UPPER(LTRIM(RTRIM(CAST([{col}] AS nvarchar(200)))))"
        frames.append(_q(f"SELECT TOP 60 {key} AS name, COUNT(*) AS n FROM dbo.[{table}] "
                         f"WHERE [{col}] LIKE ? ESCAPE '\\' GROUP BY {key} ORDER BY COUNT(*) DESC", (pattern,)))
    df = pd.concat(frames, ignore_index=True)
    return df.groupby("name", as_index=False)["n"].sum().sort_values("n", ascending=False).head(60)


@st.cache_data(ttl="30m", show_spinner=False)
def class_options(selected_rows):
    """Class labels ('MAR – Marine Cargo') found in the selected registers. selected_rows = ((table, class_col, amount_col), ...)"""
    labels = set()
    for table, class_col, amount_col in selected_rows:
        labels |= set(by_class(table, class_col, amount_col)["k"])
    return sorted(labels, key=str.casefold)


def class_code(label):
    return label.split(" – ")[0].strip()


# ------------------------------------------------------------------ row labels
def period_labels(view, year, month):
    """Row labels (in order) for the month / weekly views of one year or month."""
    if view == "Month-wise":
        return MONTHS
    last = calendar.monthrange(int(year), int(month))[1]
    mon = MONTHS[int(month) - 1]
    spans = [(s, min(s + 6, last)) for s in range(1, last + 1, 7)]
    return [f"Week {i} ({a}–{b} {mon})" for i, (a, b) in enumerate(spans, start=1)]


def bucket_labels(view, start, end):
    """[(key, label)] in date order for every month / week touching start..end."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        last = calendar.monthrange(y, m)[1]
        mon, yy = MONTHS[m - 1], f"{y % 100:02d}"
        if view == "Month-wise":
            out.append((y * 10000 + m * 100, f"{mon} {y}"))
        else:
            spans = [(s, min(s + 6, last)) for s in range(1, last + 1, 7)]
            for i, (a, b) in enumerate(spans, start=1):
                if date(y, m, b) < start or date(y, m, a) > end:        # week outside the range
                    continue
                out.append((y * 10000 + m * 100 + i, f"Week {i} ({a}–{b} {mon} {yy})"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ------------------------------------------------------------------ the comparison table
def compare(view, selected, top=10, year=None, month=None, start=None, end=None, classes=(), customers=()):
    """Wide table (rows = year / month / week / class / customer, one column per register)
    and the list of registers skipped for this view.

    selected  : rows of sources() for the chosen registers.
    year/month: for the period views when no date range is given.
    start/end : inclusive date range (datetime.date) that limits every view.
    classes   : class codes to keep (empty = all).   customers: customer names to keep (empty = all).
    """
    ranged = start is not None and end is not None
    series, skipped = [], []
    for _, s in selected.iterrows():
        t, d, a = s["table"], _none(s["date_col"]), _none(s["amount_col"])
        yc = _none(s.get("year_col"))
        needs_date = view in PERIOD_VIEWS or ranged               # months, weeks and date ranges need real dates
        if needs_date and d is None:
            skipped.append(f"{s['name']} (no date column)"); continue
        if view == "Year-wise" and d is None and yc is None:
            skipped.append(f"{s['name']} (no year or date column)"); continue
        flt = []
        if customers:
            if pd.isna(s["customer_col"]):
                skipped.append(f"{s['name']} (no customer column)"); continue
            flt.append(("in", s["customer_col"], tuple(customers)))
        if classes:
            if pd.isna(s["class_col"]):
                skipped.append(f"{s['name']} (no class column)"); continue
            flt.append(("in", s["class_col"], tuple(classes)))
        flt = tuple(flt)
        if view == "Year-wise":
            df = by_year(t, d, a, start, end, flt, yc)
        elif view in PERIOD_VIEWS:
            df = (by_bucket(t, d, a, _KIND[view], start, end, flt) if ranged
                  else by_period(t, d, a, _KIND[view], year, month, flt))
        elif view == "Class-wise":
            if pd.isna(s["class_col"]):
                skipped.append(s["name"]); continue
            df = by_class(t, s["class_col"], a, d, start, end, flt)
        else:
            if pd.isna(s["customer_col"]):
                skipped.append(s["name"]); continue
            df = by_customer(t, s["customer_col"], a, d, start, end, flt)
        series.append(df.dropna(subset=["k"]).groupby("k")["premium"].sum().rename(s["name"]))
    if not series:
        return pd.DataFrame(), skipped
    wide = pd.concat(series, axis=1)
    if view == "Year-wise":
        wide = wide.sort_index()
        wide.index.name = "Year"
    elif view in PERIOD_VIEWS:
        if ranged:
            pairs = bucket_labels(view, start, end)
            wide = wide.reindex([k for k, _ in pairs])                   # keep empty buckets visible
            wide.index = [label for _, label in pairs]
        else:
            labels = period_labels(view, year, month)
            wide = wide.reindex(range(1, len(labels) + 1))
            wide.index = labels
        wide.index.name = {"Month-wise": "Month", "Weekly": "Week"}[view]
    else:
        wide.index.name = view.split("-")[0]               # Class / Customer
        wide = wide.loc[wide.sum(axis=1).sort_values(ascending=False).head(top).index]
    return wide, skipped


def period_report_bytes(selected, year=None, month=None, start=None, end=None, classes=(), customers=()):
    """One Excel workbook with the year-wise, month-wise and weekly reports
    (for a date range if start/end are given, otherwise for the chosen year and month)."""
    f = dict(classes=classes, customers=customers)
    if start is not None and end is not None:
        tag = f"{start:%d%b%y}-{end:%d%b%y}"
        sheets = {"Year-wise": compare("Year-wise", selected, start=start, end=end, **f)[0]}
        for name, view in (("Months", "Month-wise"), ("Weeks", "Weekly")):
            sheets[f"{name} {tag}"[:31]] = compare(view, selected, start=start, end=end, **f)[0]
    else:
        mon = MONTHS[int(month) - 1]
        sheets = {
            "Year-wise": compare("Year-wise", selected, **f)[0],
            f"Months {year}": compare("Month-wise", selected, year=year, **f)[0],
            f"Weeks {mon} {year}": compare("Weekly", selected, year=year, month=month, **f)[0],
        }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, wide in sheets.items():
            out = wide.fillna(0)
            out["Total"] = out.sum(axis=1)
            out.reset_index().to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "B2"
            ws.column_dimensions["A"].width = 34
            for i in range(2, len(out.columns) + 2):
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 24
            for row in ws.iter_rows(min_row=2, min_col=2):
                for cell in row:
                    cell.number_format = "#,##0"
    return buf.getvalue()
