"""
Text-to-SQL engine for the BI Assistant Bot.

Flow for every question:
  1. pick_tables()    - the LLM chooses the 1-3 most relevant tables (from the table list only)
  2. table_schema()   - columns, types and a few sample rows of those tables
  3. generate_sql()   - the LLM writes ONE T-SQL SELECT query
  4. validate_sql()   - only read-only SELECT / WITH queries are allowed
  5. run_query()      - executes it (row-capped, with a timeout, never commits)
  6. summarize()      - the LLM explains the result in plain language

Needs GROQ_API_KEY in the .env file (see .env.example).
"""
import io
import os
import re

import pandas as pd
from dotenv import load_dotenv

from db_connector import get_engine

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_ROWS = 50_000       # rows pulled back from SQL Server (and exported to Excel)
PREVIEW_ROWS = 500      # rows shown on screen
MAX_TABLES = 3          # tables handed to the SQL-writing step
QUERY_TIMEOUT = 90      # seconds
HIDDEN_TABLES = {"_catalog", "sysdiagrams"}

_client = None


# ------------------------------------------------------------------ LLM
def get_client():
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is missing. Copy .env.example to .env and put your Groq key in it.")
        from groq import Groq
        _client = Groq(api_key=key)
    return _client


def _chat(system, human):
    reply = get_client().chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": human}])
    return (reply.choices[0].message.content or "").strip()


# ------------------------------------------------------------------ schema
def list_tables(engine=None):
    """{table_name: row_count} for every loaded data table."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT table_name, row_count FROM dbo._catalog WHERE status = 'ok'").fetchall()
    return {r[0]: (r[1] or 0) for r in rows if r[0] not in HIDDEN_TABLES}


def table_schema(tables, engine=None, sample_rows=3):
    """Text description (columns + sample rows) of the given tables."""
    engine = engine or get_engine()
    known = set(list_tables(engine))
    parts = []
    with engine.connect() as conn:
        for t in tables:
            if t not in known:          # never interpolate an unknown name into SQL
                continue
            cols = conn.exec_driver_sql(
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
                (t,)).fetchall()
            sample = pd.read_sql(f"SELECT TOP {sample_rows} * FROM [dbo].[{t}]", conn)
            sample = sample.map(lambda v: str(v)[:40])
            parts.append(
                f"TABLE dbo.[{t}]\n"
                f"  columns: " + ", ".join(f"[{c}] {d}" for c, d in cols) + "\n"
                f"  sample rows:\n" + sample.to_csv(index=False))
    return "\n".join(parts)


# ------------------------------------------------------------------ step 1: tables
def pick_tables(question, history_text=""):
    tables = list_tables()
    listing = "\n".join(f"- {name} ({rows:,} rows)" for name, rows in sorted(tables.items()))
    answer = _chat(
        "You route questions about an insurance company's MIS registers (collections, renewals, "
        "claims, targets, branch/class names) stored in SQL Server. Given the table list, reply with "
        f"ONLY the names of the 1 to {MAX_TABLES} most relevant tables, one per line, exactly as "
        "written. Prefer the most recent / most complete table for a topic. If the message is not a "
        "question about this data (greeting, thanks, general chat), reply with exactly: NONE",
        f"Tables:\n{listing}\n\nConversation so far:\n{history_text or '(none)'}\n\nQuestion: {question}")
    if answer.strip().upper().startswith("NONE"):
        return []
    picked = [n for n in tables if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", answer)]
    return picked[:MAX_TABLES]


# ------------------------------------------------------------------ step 3: SQL
SQL_RULES = """You write ONE Microsoft SQL Server (T-SQL) query that answers the question.
Rules:
- Output ONLY the SQL, no explanation, no markdown fences.
- Use only the tables and columns shown. Quote identifiers like dbo.[Table] and [Column].
- T-SQL syntax: use TOP n (never LIMIT), YEAR()/MONTH(), FORMAT(), GETDATE().
- Many numeric fields (e.g. Premium, SumInsured, AmountPaid) are stored as nvarchar: wrap them with
  TRY_CAST([Col] AS float) before summing, averaging or comparing.
- Dates are datetime columns; filter them with ranges or YEAR()/MONTH().
- Prefer aggregated answers (SUM/COUNT/GROUP BY, ORDER BY ... DESC) over dumping raw rows; if you do
  return raw rows, use SELECT TOP 100.
- A single read-only SELECT (CTEs allowed). Never modify data."""


def _strip_fences(sql):
    sql = re.sub(r"^```(?:sql|tsql)?\s*|\s*```$", "", sql.strip(), flags=re.I)
    return sql.strip()


def generate_sql(question, schema, history_text="", error=None, previous_sql=None):
    human = (f"{schema}\n\nConversation so far:\n{history_text or '(none)'}\n\nQuestion: {question}")
    if error:
        human += (f"\n\nYour previous query failed.\nQuery:\n{previous_sql}\nError:\n{error}\n"
                  "Write a corrected query.")
    return _strip_fences(_chat(SQL_RULES, human))


# ------------------------------------------------------------------ step 4: safety
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|exec|execute|grant|revoke|deny|"
    r"backup|restore|shutdown|openrowset|openquery|opendatasource|bulk|into|use|waitfor|dbcc|"
    r"xp_\w+|sp_\w+)\b", re.I)


def validate_sql(sql):
    """Return the cleaned query or raise ValueError if it is not a safe single SELECT."""
    cleaned = re.sub(r"--[^\n]*", " ", sql)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.S).strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty query.")
    if ";" in cleaned:
        raise ValueError("Only a single statement is allowed.")
    if not re.match(r"(select|with)\b", cleaned, re.I):
        raise ValueError("Only SELECT queries are allowed.")
    # ignore text inside quotes when looking for forbidden keywords
    unquoted = re.sub(r"'(?:[^']|'')*'", "''", cleaned)
    bad = _FORBIDDEN.search(unquoted)
    if bad:
        raise ValueError(f"Keyword not allowed: {bad.group(0)}")
    return cleaned


# ------------------------------------------------------------------ step 5: run
def run_query(sql, engine=None):
    """Execute a validated query. Returns (DataFrame, was_truncated). Never commits."""
    engine = engine or get_engine()
    sql = validate_sql(sql)
    with engine.connect() as conn:
        try:
            conn.connection.dbapi_connection.timeout = QUERY_TIMEOUT
        except Exception:
            pass
        result = conn.exec_driver_sql(sql)
        rows = result.fetchmany(MAX_ROWS + 1)
        df = pd.DataFrame([tuple(r) for r in rows], columns=list(result.keys()))
        conn.rollback()
    truncated = len(df) > MAX_ROWS
    return df.head(MAX_ROWS), truncated


# ------------------------------------------------------------------ step 6: explain
def summarize(question, sql, df, truncated):
    if df.empty:
        data_text = "(the query returned no rows)"
    else:
        data_text = df.head(30).to_csv(index=False)[:6000]
    return _chat(
        "You are the BI Assistant Bot, a business-intelligence assistant for MIS data. Answer the question clearly and briefly using ONLY the query "
        "result. Give the key numbers (format large numbers with thousands separators). Do not invent "
        "figures. If the result is empty, say no matching data was found. Mention if results were cut off. "
        "The app shows a 'Download Excel' button under your answer, so never say you cannot create "
        "files or reports; if the user wants a report, tell them to use that button.",
        f"Question: {question}\n\nSQL used:\n{sql}\n\nResult ({len(df)} rows"
        f"{', truncated' if truncated else ''}):\n{data_text}")


def chat_only(question, history_text=""):
    return _chat(
        "You are a friendly assistant for an insurance company's MIS data (collection, renewal, claim "
        "and target registers). Reply briefly. If useful, suggest the kind of question you can answer "
        "from the data. This app CAN produce Excel reports: every answer that returns data has a "
        "'Download Excel' button, and users can paste their own SQL SELECT query to get its output "
        "as a report. Never say you cannot create files; explain this instead.",
        f"Conversation so far:\n{history_text or '(none)'}\n\nUser: {question}")


# ------------------------------------------------------------------ Excel report
def extract_sql(text_):
    """If the user pasted their own SQL (fenced block, or a message that is a SELECT/WITH), return it."""
    m = re.search(r"```(?:sql|tsql)?\s*(.*?)```", text_, re.S | re.I)
    candidate = (m.group(1) if m else text_).strip()
    return candidate if re.match(r"(select|with)\b", candidate, re.I) else None


def to_excel_bytes(df, sql=None, sheet_name="Report"):
    """Build an .xlsx file (data sheet + a sheet with the SQL used) and return its bytes."""
    from openpyxl.styles import Font
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name=sheet_name, index=False)
        ws = xw.sheets[sheet_name]
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for i, col in enumerate(df.columns, start=1):
            width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 50)
        if sql:
            pd.DataFrame({"SQL used": sql.splitlines()}).to_excel(xw, sheet_name="Query", index=False)
            xw.sheets["Query"].column_dimensions["A"].width = 120
    return buf.getvalue()


# ------------------------------------------------------------------ orchestration
def format_history(history, limit=6):
    """history: list of {'role': 'user'|'assistant', 'content': str}"""
    return "\n".join(f"{m['role']}: {m['content'][:500]}" for m in (history or [])[-limit:])


def ask(question, history=None):
    """Full pipeline. Returns dict(answer, sql, data, tables, truncated, error)."""
    history_text = format_history(history)
    out = {"answer": "", "sql": None, "data": None, "tables": [], "truncated": False, "error": None}

    own_sql = extract_sql(question)               # user pasted their own query: run it as given
    if own_sql:
        try:
            df, truncated = run_query(own_sql)
            out.update(sql=validate_sql(own_sql), data=df, truncated=truncated)
            out["answer"] = summarize("Run the SQL query I provided", out["sql"], df, truncated)
        except Exception as e:                    # noqa: BLE001
            out.update(sql=own_sql, error=str(e).split("\n")[0][:500],
                       answer="That query could not be run.")
        return out

    tables = pick_tables(question, history_text)
    out["tables"] = tables
    if not tables:
        out["answer"] = chat_only(question, history_text)
        return out

    schema = table_schema(tables)
    sql = generate_sql(question, schema, history_text)
    last_error = None
    for attempt in range(2):                       # one automatic retry with the error message
        try:
            df, truncated = run_query(sql)
            out.update(sql=validate_sql(sql), data=df, truncated=truncated)
            out["answer"] = summarize(question, out["sql"], df, truncated)
            return out
        except Exception as e:                      # noqa: BLE001 - report any SQL/validation error
            last_error = str(e).split("\n")[0][:500]
            if attempt == 0:
                sql = generate_sql(question, schema, history_text, error=last_error, previous_sql=sql)
    out["sql"] = sql
    out["error"] = last_error
    out["answer"] = ("I couldn't get a valid result for that question. "
                     "Try rephrasing it, or name the table/year you mean.")
    return out
