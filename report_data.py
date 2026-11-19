"""
Data access for the Excel report generator and the pivot generator.

Everything is built from a small "pivot spec":
    table, date_col      the sheet/table to read and its main date column
    row_field, col_field ("text", column) | ("year", None) | ("month", None); col_field may be None
    value_col            a column to aggregate (numbers stored as text are fine), or None = count rows
    agg                  Sum | Count | Average | Min | Max
    date_range           (start, end) or None
    filters              (("in", column, (values...)), ("like", column, "text"), ...)

aggregate() returns the pivot as a table (values straight from SQL Server);
raw_rows() returns the underlying rows, which the Excel builder writes to a data sheet so the pivot
cells can be real SUMIFS / COUNTIFS formulas.
"""
import re

import pandas as pd
import streamlit as st

import glance_data as gd
import summary_data as sm
from common import shared_engine

MAX_RAW_ROWS = 100_000          # most rows written to a data sheet (formula reports)
MAX_PIVOT_ROWS = 500
MAX_PIVOT_COLS = 60
MONTHS = sm.MONTHS
AGGS = ("Sum", "Count", "Average", "Min", "Max")
BLANK = "(blank)"
DATE_TYPES = gd._DATE_TYPES
_AMOUNT_HINT = re.compile(r"prem|amount|paid|insured|net|gross|total|target|collection|commission|vat|tax|"
                          r"balance|value|price|qty|quantity", re.I)


def _run(sql, params=()):
    with shared_engine().connect() as conn:
        res = conn.exec_driver_sql(sql, tuple(params))
        return pd.DataFrame([tuple(r) for r in res.fetchall()], columns=list(res.keys()))


def _escape_like(text):
    return re.sub(r"([\\%_\[])", r"\\\1", text)


# ------------------------------------------------------------------ tables, columns and their roles
@st.cache_data(ttl="30m", show_spinner=False)
def table_columns():
    """{table: [(column, type), ...]} for every table in the Register database."""
    df = _run("SELECT TABLE_NAME AS t, COLUMN_NAME AS c, DATA_TYPE AS d FROM INFORMATION_SCHEMA.COLUMNS "
              "WHERE TABLE_SCHEMA = 'dbo' ORDER BY TABLE_NAME, ORDINAL_POSITION")
    return {t: list(zip(g["c"], g["d"].str.lower())) for t, g in df.groupby("t")}


def roles(table):
    """Which columns hold the date, the amount, the class and the customer."""
    cs = table_columns().get(table, [])
    label, amount_col, _ = gd._pick_amount_col(cs)
    return {"date_col": gd._pick_date_col(cs), "amount_label": label, "amount_col": amount_col,
            "class_col": next((n for n, _ in cs if sm._CLASS_RE.search(n)), None),
            "customer_col": next((n for n, _ in cs if sm._CUSTOMER_RE.search(n)), None)}


def amount_like(column):
    return bool(_AMOUNT_HINT.search(column))


@st.cache_data(ttl="30m", show_spinner=False)
def sources_by_label(label):
    """Registers whose main sheet has a date, class, customer and an amount called `label`
    ('Premium' for collection registers, 'Amount paid' for the claim register)."""
    out = []
    for _, r in gd.registers().iterrows():
        for table in r["tables"]:
            ro = roles(table)
            if ro["amount_label"] == label and ro["date_col"] and ro["class_col"] and ro["customer_col"]:
                out.append({"name": r["name"], "category": r["category"], "table": table, **ro})
                break
    return pd.DataFrame(out)


@st.cache_data(ttl="10m", show_spinner=False)
def find_customers(text, sources):
    """Customer names containing `text`, with how many rows each has. sources = ((table, customer_col), ...)"""
    pattern = f"%{_escape_like(text.strip())}%"
    frames = []
    for table, col in sources:
        key = f"UPPER(LTRIM(RTRIM(CAST([{col}] AS nvarchar(200)))))"
        frames.append(_run(f"SELECT TOP 60 {key} AS name, COUNT(*) AS n FROM dbo.[{table}] "
                           f"WHERE [{col}] LIKE ? ESCAPE '\\' GROUP BY {key} ORDER BY COUNT(*) DESC", (pattern,)))
    df = pd.concat(frames, ignore_index=True)
    return df.groupby("name", as_index=False)["n"].sum().sort_values("n", ascending=False).head(60)


@st.cache_data(ttl="10m", show_spinner=False)
def distinct_values(table, column, limit=300):
    """The most common values of a column (for filter pick-lists)."""
    key = f"UPPER(LTRIM(RTRIM(CAST([{column}] AS nvarchar(200)))))"
    return _run(f"SELECT TOP {int(limit)} {key} AS value, COUNT(*) AS n FROM dbo.[{table}] "
                f"WHERE [{column}] IS NOT NULL GROUP BY {key} ORDER BY COUNT(*) DESC")


@st.cache_data(ttl="30m", show_spinner=False)
def cardinality(table, column):
    """How many different values a column has (decides between a pick-list and a search box)."""
    key = f"UPPER(LTRIM(RTRIM(CAST([{column}] AS nvarchar(200)))))"
    return int(_run(f"SELECT COUNT(DISTINCT {key}) AS n FROM dbo.[{table}] WHERE [{column}] IS NOT NULL")["n"].iloc[0])


@st.cache_data(ttl="10m", show_spinner=False)
def find_values(table, column, text, limit=60):
    """Values of a column containing `text` (most common first), for columns with too many values to list."""
    key = f"UPPER(LTRIM(RTRIM(CAST([{column}] AS nvarchar(200)))))"
    return _run(f"SELECT TOP {int(limit)} {key} AS value, COUNT(*) AS n FROM dbo.[{table}] "
                f"WHERE [{column}] LIKE ? ESCAPE '\\' GROUP BY {key} ORDER BY COUNT(*) DESC",
                (f"%{_escape_like(text.strip())}%",))


@st.cache_data(ttl="30m", show_spinner=False)
def year_values(table, date_col):
    """The years that have data, with row counts."""
    return _run(f"SELECT YEAR([{date_col}]) AS value, COUNT(*) AS n FROM dbo.[{table}] "
                f"WHERE [{date_col}] IS NOT NULL GROUP BY YEAR([{date_col}]) ORDER BY 1")


# ------------------------------------------------------------------ building the SQL
_MONTH_SQL = "CHOOSE(MONTH([{d}]), " + ", ".join(f"N'{m}'" for m in MONTHS) + ")"


def _part_sql(field, date_col):
    """One field as text that is never NULL (used when several fields are combined into one label)."""
    kind, col = field
    if kind == "year":
        return f"ISNULL(CAST(YEAR([{date_col}]) AS nvarchar(10)), N'{BLANK}')"
    if kind == "month":
        return f"ISNULL({_MONTH_SQL.format(d=date_col)}, N'{BLANK}')"
    return f"ISNULL(NULLIF(LTRIM(RTRIM(CAST([{col}] AS nvarchar(200)))), N''), N'{BLANK}')"


def _expr(field, date_col):
    kind, col = field
    if kind == "combo":                                # several fields ticked: "GHI | B"
        return " + N' | ' + ".join(_part_sql(f, date_col) for f in col)
    if kind == "all":                                  # no breakdown: one row for everything
        return "'All'"
    if kind == "year":
        return f"YEAR([{date_col}])"
    if kind == "month":
        return f"MONTH([{date_col}])"
    return f"LTRIM(RTRIM(CAST([{col}] AS nvarchar(200))))"


def _where(date_col, date_range, filters):
    conds, params = [], []
    if date_range and date_col:
        conds.append(f"[{date_col}] >= ? AND [{date_col}] < DATEADD(day, 1, ?)")
        params += [date_range[0], date_range[1]]
    for kind, col, values in filters:
        if kind == "in" and values:
            marks = ",".join("?" * len(values))
            conds.append(f"UPPER(LTRIM(RTRIM(CAST([{col}] AS nvarchar(200))))) IN ({marks})")
            params += [str(v).strip().upper() for v in values]
        elif kind == "like" and values:
            conds.append(f"[{col}] LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(str(values))}%")
        elif kind in ("year", "month") and values and date_col:      # picked years / months of the date column
            marks = ",".join("?" * len(values))
            conds.append(f"{kind.upper()}([{date_col}]) IN ({marks})")
            params += [int(v) for v in values]
    return ("WHERE " + " AND ".join(conds)) if conds else "", params


def _norm(series, field):
    """Turn SQL values into the labels used in the report (year -> int, month -> 'Jan', blank -> '(blank)')."""
    kind = field[0] if field else "text"
    def one(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return BLANK
        if kind == "year":
            return int(v)
        if kind == "month":
            return MONTHS[int(v) - 1]
        s = str(v).strip()
        return s if s else BLANK
    return series.map(one)


def _part_order(field, value):
    kind = field[0]
    if kind == "month":
        return MONTHS.index(value) if value in MONTHS else 99
    if kind == "year":
        return int(value) if str(value).isdigit() else 9999
    return str(value).casefold()


def _sorted_keys(keys, field):
    kind = field[0] if field else "text"
    ks = list(dict.fromkeys(keys))
    if kind == "combo":                                # sort each part its own way (months in calendar order, ...)
        parts = field[1]
        def order(key):
            bits = str(key).split(" | ")
            return tuple((b == BLANK, _part_order(f, b)) for f, b in zip(parts, bits))
        return sorted(ks, key=order)
    if kind == "month":
        return sorted(ks, key=lambda k: (k == BLANK, MONTHS.index(k) if k in MONTHS else 99))
    if kind == "year":
        return sorted(ks, key=lambda k: (k == BLANK, k if k != BLANK else 0))
    return sorted(ks, key=lambda k: (k == BLANK, str(k).casefold()))


_AGG_SQL = {"Sum": "SUM(v)", "Count": "COUNT(*)", "Average": "AVG(v)", "Min": "MIN(v)", "Max": "MAX(v)"}
_AGG_PD = {"Sum": "sum", "Count": "sum", "Average": "mean", "Min": "min", "Max": "max"}


@st.cache_data(ttl="10m", show_spinner=False)
def aggregate(table, date_col, row_field, col_field, value_col, agg, date_range=None, filters=(),
              sort_rows="Label"):
    """The pivot: {'wide': rows x columns table, 'row_tot', 'col_tot', 'grand'}. Raises ValueError if too big."""
    where, params = _where(date_col, date_range, filters)
    rx = _expr(row_field, date_col)
    cx = _expr(col_field, date_col) if col_field else "'Total'"
    vx = f"TRY_CAST([{value_col}] AS float)" if value_col else "1"
    inner = f"(SELECT {rx} AS r, {cx} AS c, {vx} AS v FROM dbo.[{table}] {where}) x"
    fn = _AGG_SQL[agg]

    cells = _run(f"SELECT r, c, {fn} AS val FROM {inner} GROUP BY r, c", params)
    cells["r"], cells["c"] = _norm(cells["r"], row_field), _norm(cells["c"], col_field)
    cells = cells.groupby(["r", "c"], as_index=False)["val"].agg(_AGG_PD[agg])
    rows = _sorted_keys(cells["r"], row_field)
    cols = _sorted_keys(cells["c"], col_field)
    if len(rows) > MAX_PIVOT_ROWS:
        raise ValueError(f"The rows field has {len(rows):,} different values (limit {MAX_PIVOT_ROWS}). "
                         "Pick a field with fewer values or add a filter.")
    if len(cols) > MAX_PIVOT_COLS:
        raise ValueError(f"The columns field has {len(cols):,} different values (limit {MAX_PIVOT_COLS}). "
                         "Pick a field with fewer values or add a filter.")
    wide = cells.pivot(index="r", columns="c", values="val").reindex(index=rows, columns=cols)
    if agg in ("Sum", "Count"):
        wide = wide.fillna(0)
        row_tot, col_tot, grand = wide.sum(axis=1), wide.sum(axis=0), float(wide.to_numpy().sum())
    else:                                                  # totals can't be derived from the cells
        def totals(select, group):
            df = _run(f"SELECT {select}{fn} AS val FROM {inner}{group}", params)
            return df
        rt = totals("r, ", " GROUP BY r"); rt["r"] = _norm(rt["r"], row_field)
        ct = totals("c, ", " GROUP BY c"); ct["c"] = _norm(ct["c"], col_field)
        row_tot = rt.groupby("r")["val"].agg(_AGG_PD[agg]).reindex(rows)
        col_tot = ct.groupby("c")["val"].agg(_AGG_PD[agg]).reindex(cols)
        gv = totals("", "")["val"].iloc[0]
        grand = None if pd.isna(gv) else float(gv)
    if sort_rows != "Label" and len(rows) > 1:
        order = row_tot.sort_values(ascending=False).index
        wide, row_tot = wide.loc[order], row_tot.loc[order]
    return {"wide": wide, "row_tot": row_tot, "col_tot": col_tot, "grand": grand}


@st.cache_data(ttl="10m", show_spinner=False)
def raw_rows(table, date_col, row_field, col_field, value_col, date_range=None, filters=(),
             limit=MAX_RAW_ROWS):
    """The rows behind the pivot (row_key, col_key, value) and whether they were cut at `limit`."""
    where, params = _where(date_col, date_range, filters)
    rx = _expr(row_field, date_col)
    cx = _expr(col_field, date_col) if col_field else "'Total'"
    vx = f"TRY_CAST([{value_col}] AS float)" if value_col else "1"
    df = _run(f"SELECT TOP {int(limit) + 1} {rx} AS row_key, {cx} AS col_key, {vx} AS value "
              f"FROM dbo.[{table}] {where}", params)
    truncated = len(df) > limit
    df = df.head(limit).copy()
    df["row_key"], df["col_key"] = _norm(df["row_key"], row_field), _norm(df["col_key"], col_field)
    return df, truncated
