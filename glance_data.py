"""
Data layer for the "At a glance" page: one summary per register (source file) loaded
into the Register database, read from public._catalog plus a few light aggregate queries.

Per register it returns: rows, sheets/tables, columns, date coverage, a headline total
(premium / amount paid / target ...), when the source file changed and when it was loaded.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from common import shared_engine
from db_connector import qi

CATEGORY_ORDER = ["Collection", "Renewal", "Claims", "Targets & campaigns",
                  "Bancassurance", "Reference lists", "Other"]

_DATE_TYPES = {"date", "timestamp without time zone", "timestamp with time zone"}
_NUM_TYPES = {"double precision", "real", "numeric", "integer", "bigint", "smallint"}
_TEXT_TYPES = {"text", "character varying"}

# (label shown on the tile, regex on the lower-cased column name) - first match wins
_AMOUNT_RULES = [
    ("Premium", r"premium|credit_net"),
    ("Amount paid", r"amount_?paid"),
    ("Target", r"target"),
    ("Collection", r"collection"),
    ("Total renewal", r"total_?renewal"),
    ("Total", r"^total$"),
]
_DATE_RULES = [r"credit", r"payment", r"doc_?date", r"^date$", r"date"]


# ------------------------------------------------------------------ helpers
def compact(value):
    """1234567 -> '1.23M'. None/NaN -> an em dash."""
    if value is None or pd.isna(value):
        return "—"
    a = abs(value)
    for div, suffix, digits in ((1e9, "B", 2), (1e6, "M", 2), (1e3, "K", 1)):
        if a >= div:
            return f"{value / div:,.{digits}f}{suffix}"
    return f"{value:,.0f}"


def categorize(file_name):
    n = file_name.lower()
    if n.startswith("name"):
        return "Reference lists"
    if "claim" in n:
        return "Claims"
    if "banca" in n:
        return "Bancassurance"
    if "renewal" in n:
        return "Renewal"
    if any(k in n for k in ("target", "campaign", "hunt")):
        return "Targets & campaigns"
    if "collection" in n or n.startswith("cr_"):
        return "Collection"
    return "Other"


def clean_name(file_name):
    stem = os.path.splitext(file_name)[0]
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()


def _query(engine, sql):
    with engine.connect() as conn:
        res = conn.exec_driver_sql(sql)
        return pd.DataFrame([tuple(r) for r in res.fetchall()], columns=list(res.keys()))


def _pick_date_col(cols):
    dates = [c for c, d in cols if d in _DATE_TYPES]
    for rule in _DATE_RULES:
        for c in dates:
            if re.search(rule, c.lower()):
                return c
    return dates[0] if dates else None


def _pick_amount_col(cols):
    usable = [(c, d) for c, d in cols if d in _NUM_TYPES | _TEXT_TYPES]
    for label, rule in _AMOUNT_RULES:
        for c, d in usable:
            if re.search(rule, c.lower()):
                return label, c, d
    return None, None, None


def _profile(engine, table, cols):
    """Date coverage + headline total for one table. Never raises."""
    out = {"date_col": None, "date_min": pd.NaT, "date_max": pd.NaT,
           "amount_label": None, "amount_col": None, "amount_sum": None}
    date_col = _pick_date_col(cols)
    label, amt_col, amt_type = _pick_amount_col(cols)
    if not date_col and not amt_col:
        return out
    parts, names = [], []
    if date_col:
        ok = f"d BETWEEN '2000-01-01' AND '2100-01-01'"   # ignore junk dates like 1900-01-01
        parts += [f"MIN(CASE WHEN {ok} THEN d END)", f"MAX(CASE WHEN {ok} THEN d END)"]
        names += ["date_min", "date_max"]
    if amt_col:
        parts.append("SUM(v)")
        names.append("amount_sum")
    inner = []
    if date_col:
        inner.append(f"{qi(date_col)} AS d")
    if amt_col:
        inner.append(f"try_float({qi(amt_col)}::text) AS v")
    sql = f"SELECT {', '.join(parts)} FROM (SELECT {', '.join(inner)} FROM {qi(table)}) x"
    try:
        row = _query(engine, sql).iloc[0]
        for i, n in enumerate(names):
            v = row.iloc[i]
            out[n] = pd.Timestamp(v) if n in ("date_min", "date_max") and pd.notna(v) else v
        out.update(date_col=date_col, amount_label=label, amount_col=amt_col)
    except Exception:  # noqa: BLE001 - a bad table must not break the whole page
        pass
    return out


# ------------------------------------------------------------------ public API
@st.cache_data(ttl="30m", show_spinner="Summarising registers...")
def registers():
    """One row per register (source file), with profile columns. Cached for 30 minutes."""
    engine = shared_engine()
    cat = _query(engine, "SELECT table_name, source_path, sheet_name, file_mtime, row_count, "
                         "column_count, loaded_at FROM public._catalog WHERE status = 'ok'")
    cols = _query(engine, "SELECT TABLE_NAME AS t, COLUMN_NAME AS c, DATA_TYPE AS d "
                          "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'public' "
                          "ORDER BY TABLE_NAME, ORDINAL_POSITION")
    colmap = {t: list(zip(g["c"], g["d"].str.lower())) for t, g in cols.groupby("t")}

    cat["file"] = cat["source_path"].map(os.path.basename)
    cat["folder"] = cat["source_path"].map(lambda p: os.path.basename(os.path.dirname(p)))
    with ThreadPoolExecutor(max_workers=4) as pool:      # the 1M-row tables take a few seconds each
        profiles = list(pool.map(lambda t: _profile(engine, t, colmap.get(t, [])), cat["table_name"]))
    cat = pd.concat([cat.reset_index(drop=True), pd.DataFrame(profiles)], axis=1)
    cat = cat.sort_values("row_count", ascending=False)   # biggest sheet first

    out = []
    for path, g in cat.groupby("source_path", sort=False):
        main = g.iloc[0]                                   # biggest sheet = the register itself
        dated = g[g["date_min"].notna()]                   # first sheet that has dates / an amount
        amount = g[g["amount_sum"].notna()]
        d = dated.iloc[0] if len(dated) else None
        a = amount.iloc[0] if len(amount) else None
        out.append({
            "source_path": path, "file": main["file"], "folder": main["folder"],
            "name": clean_name(main["file"]), "category": categorize(main["file"]),
            "tables": list(g["table_name"]),               # biggest sheet first
            "sheets": len(g), "rows": int(g["row_count"].sum()),
            "columns": int(main["column_count"]), "file_updated": g["file_mtime"].max(),
            "loaded": g["loaded_at"].max(),
            "date_min": d["date_min"] if d is not None else pd.NaT,
            "date_max": d["date_max"] if d is not None else pd.NaT,
            "amount_label": a["amount_label"] if a is not None else None,
            "amount_sum": a["amount_sum"] if a is not None else None,
        })
    return pd.DataFrame(out)


@st.cache_data(ttl="30m")
def catalog_table():
    """Every loaded table (sheet) with its source file - for the detail table."""
    df = _query(shared_engine(),
                "SELECT table_name, source_path, sheet_name, row_count, column_count, "
                "file_mtime, loaded_at FROM public._catalog WHERE status = 'ok' ORDER BY table_name")
    df["file"] = df["source_path"].map(os.path.basename)
    return df.drop(columns="source_path")
