"""
Load MIS register files (Excel / CSV) into the SQL Server database [Register].

Source  : <MIS - Documents>\\Power BI Datasets, Old Registers, CR_Merged_OLD_NEW_CIS
Target  : SQL Server  localhost\\SQLEXPRESS  ->  database [Register]
Layout  : one table per file (or per sheet when a workbook has several sheets)
Catalog : dbo._catalog lists every table, its source file/sheet, row count and status
Log     : etl\\logs\\load_register_<timestamp>.log

Re-running is safe: a file whose modified time hasn't changed since its last
successful load is skipped, so this can run daily from Task Scheduler.
Use  --full  to force reloading everything.
"""
import argparse
import datetime as dt
import importlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- settings
SERVER = r"localhost\SQLEXPRESS"
DATABASE = "Register"
MIS_ROOT = Path(os.path.expanduser(
    r"~\GDIC\OneDrive - Green Delta Insurance PLC\Shortcuts\MIS - Documents"))
FOLDERS = {                       # folder -> table-name prefix
    "Power BI Datasets": "PBI",
    "Old Registers": "OLD",
    "CR_Merged_OLD_NEW_CIS": "CR",
}
EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".xlsb", ".csv"}
CSV_CHUNK = 100_000
SQL_CHUNK = 5_000

HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"load_register_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
STATUS_FILE = LOG_DIR / "last_run_status.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("register")


# ---------------------------------------------------------------- packages
REQUIRED = {"pandas": "pandas", "sqlalchemy": "sqlalchemy", "pyodbc": "pyodbc",
            "python_calamine": "python-calamine"}


def ensure_packages():
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return
    log.info("Installing missing packages into this Python: %s", ", ".join(missing))
    cmds = [[sys.executable, "-m", "pip", "install", "--upgrade", *missing]]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True)
        log.info(r.stdout[-2000:])
        if r.returncode != 0:
            log.error(r.stderr[-3000:])
            raise SystemExit("Package install failed - see log above.")


# ---------------------------------------------------------------- helpers
def clean_name(text, maxlen=60):
    s = re.sub(r"[^0-9A-Za-z]+", "_", str(text)).strip("_")
    s = re.sub(r"_+", "_", s)
    return (s or "x")[:maxlen]


def unique_columns(cols):
    seen, out = {}, []
    for i, c in enumerate(cols):
        name = clean_name(c, 100) if str(c).strip() not in ("", "nan", "None") else f"col_{i+1}"
        base, n = name, 1
        while name.lower() in seen:
            n += 1
            name = f"{base}_{n}"
        seen[name.lower()] = True
        out.append(name)
    return out


def find_header_row(rows, scan=15):
    """Pick the row (in the first `scan`) with the most non-empty text cells."""
    best, best_score = 0, -1
    for i, r in enumerate(rows[:scan]):
        vals = [v for v in r if str(v).strip() != ""]
        texty = [v for v in vals if isinstance(v, str)]
        score = len(texty) * 2 + len(vals)
        if len(vals) >= 2 and score > best_score:
            best, best_score = i, score
    return best


def _as_text(v):
    """Text form for mixed columns: 1812031.0 -> '1812031', dates -> 'YYYY-MM-DD'."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S") if (v.hour or v.minute or v.second) else v.strftime("%Y-%m-%d")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    return str(v)


def tidy_frame(df):
    import pandas as pd
    df = df.dropna(how="all").dropna(axis=1, how="all")
    for c in df.columns:
        s = df[c]
        if s.dtype == object:
            s = s.replace({"": None})
            nonnull = s.dropna()
            if len(nonnull) and nonnull.map(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)).all():
                s = pd.to_numeric(s, errors="coerce")
            elif len(nonnull) and nonnull.map(lambda v: isinstance(v, (dt.date, dt.datetime))).all():
                s = pd.to_datetime(s, errors="coerce")
            else:
                s = s.map(_as_text)
            df[c] = s
    return df


def sql_types(df):
    import pandas as pd
    from sqlalchemy.types import NVARCHAR, Float, BigInteger, DateTime
    types = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            types[c] = DateTime()
        elif pd.api.types.is_integer_dtype(s):
            types[c] = BigInteger()
        elif pd.api.types.is_numeric_dtype(s):
            types[c] = Float()
        else:
            ln = int(s.dropna().astype(str).str.len().max() or 1)
            types[c] = NVARCHAR(None if ln > 4000 else max(50, min(4000, ln * 2)))
    return types


# ---------------------------------------------------------------- database
def make_engines():
    import pyodbc
    from sqlalchemy import create_engine
    from urllib.parse import quote_plus
    drivers = [d for d in pyodbc.drivers()]
    log.info("ODBC drivers on this PC: %s", drivers)
    for pref in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
                 "SQL Server Native Client 11.0", "SQL Server"):
        if pref in drivers:
            driver = pref
            break
    else:
        raise SystemExit("No SQL Server ODBC driver found. Install 'ODBC Driver 18 for SQL Server'.")
    log.info("Using driver: %s", driver)

    def conn_str(db):
        return (f"DRIVER={{{driver}}};SERVER={SERVER};DATABASE={db};"
                "Trusted_Connection=yes;TrustServerCertificate=yes;Encrypt=no")

    # create the database if needed (autocommit)
    cn = pyodbc.connect(conn_str("master"), autocommit=True)
    cn.execute(f"IF DB_ID(N'{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}];")
    cn.close()
    log.info("Database [%s] is ready on %s", DATABASE, SERVER)

    fast = driver.startswith("ODBC Driver")
    eng = create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(conn_str(DATABASE)),
                        fast_executemany=fast)
    with eng.begin() as c:
        c.exec_driver_sql("""
        IF OBJECT_ID('dbo._catalog') IS NULL
        CREATE TABLE dbo._catalog (
            table_name   NVARCHAR(128) NOT NULL PRIMARY KEY,
            source_path  NVARCHAR(1000) NOT NULL,
            sheet_name   NVARCHAR(200) NULL,
            file_mtime   DATETIME2 NULL,
            row_count    BIGINT NULL,
            column_count INT NULL,
            status       NVARCHAR(20) NOT NULL,
            message      NVARCHAR(2000) NULL,
            loaded_at    DATETIME2 NOT NULL DEFAULT SYSDATETIME()
        );""")
    return eng


def record(eng, table, path, sheet, mtime, rows, cols, status, msg=None):
    with eng.begin() as c:
        c.exec_driver_sql("DELETE FROM dbo._catalog WHERE table_name = ?", (table,))
        c.exec_driver_sql(
            "INSERT INTO dbo._catalog (table_name, source_path, sheet_name, file_mtime, row_count,"
            " column_count, status, message) VALUES (?,?,?,?,?,?,?,?)",
            (table, str(path), sheet, mtime, rows, cols, status, (msg or "")[:2000]))


def already_loaded(eng, path, mtime):
    with eng.connect() as c:
        r = c.exec_driver_sql(
            "SELECT COUNT(*) FROM dbo._catalog WHERE source_path = ? AND file_mtime = ? AND status = 'ok'",
            (str(path), mtime)).scalar()
    return r > 0


def write_frame(eng, df, table, first=True):
    df.to_sql(table, eng, schema="dbo", if_exists="replace" if first else "append",
              index=False, chunksize=SQL_CHUNK, dtype=sql_types(df) if first else None)


# ---------------------------------------------------------------- loaders
def load_excel(eng, path, prefix, mtime):
    import pandas as pd
    from python_calamine import CalamineWorkbook
    wb = CalamineWorkbook.from_path(str(path))
    sheets = wb.sheet_names
    base = f"{prefix}_{clean_name(path.stem)}"
    results = []
    for s in sheets:
        table = base if len(sheets) == 1 else f"{base}__{clean_name(s, 40)}"
        table = table[:128]
        try:
            rows = wb.get_sheet_by_name(s).to_python(skip_empty_area=False)
            if not rows or len(rows) < 2:
                record(eng, table, path, s, mtime, 0, 0, "skipped", "empty sheet")
                log.info("   - %-55s skipped (empty)", table)
                continue
            h = find_header_row(rows)
            df = pd.DataFrame(rows[h + 1:], columns=unique_columns(rows[h]))
            df = tidy_frame(df)
            if df.empty:
                record(eng, table, path, s, mtime, 0, 0, "skipped", "no data rows")
                log.info("   - %-55s skipped (no data)", table)
                continue
            write_frame(eng, df, table)
            record(eng, table, path, s, mtime, len(df), df.shape[1], "ok",
                   f"header row {h+1}")
            log.info("   - %-55s %9d rows  %3d cols", table, len(df), df.shape[1])
            results.append((table, len(df)))
        except Exception as e:
            record(eng, table, path, s, mtime, None, None, "error", repr(e))
            log.error("   - %-55s ERROR %r", table, e)
    return results


def load_csv(eng, path, prefix, mtime):
    import pandas as pd
    table = f"{prefix}_{clean_name(path.stem)}"[:128]
    enc = "utf-8-sig"
    try:
        pd.read_csv(path, nrows=5, encoding=enc)
    except UnicodeDecodeError:
        enc = "cp1252"
    # pass 1: decide column types over the whole file
    numeric, dates, maxlen, cols = {}, {}, {}, None
    for chunk in pd.read_csv(path, dtype=str, chunksize=CSV_CHUNK, encoding=enc,
                             keep_default_na=False, na_values=[""], low_memory=False):
        if cols is None:
            cols = list(chunk.columns)
            numeric = {c: True for c in cols}
            dates = {c: True for c in cols}
            maxlen = {c: 1 for c in cols}
        for c in cols:
            s = chunk[c].dropna()
            if s.empty:
                continue
            maxlen[c] = max(maxlen[c], int(s.str.len().max()))
            if numeric[c] and pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce").isna().any():
                numeric[c] = False
            if dates[c] and (numeric[c] or pd.to_datetime(s, errors="coerce", format="mixed").isna().any()):
                dates[c] = False
    newcols = unique_columns(cols)
    rename = dict(zip(cols, newcols))
    from sqlalchemy.types import NVARCHAR, Float, DateTime
    dtype = {}
    for c in cols:
        n = rename[c]
        if numeric[c]:
            dtype[n] = Float()
        elif dates[c]:
            dtype[n] = DateTime()
        else:
            dtype[n] = NVARCHAR(None if maxlen[c] > 4000 else max(50, min(4000, maxlen[c] * 2)))
    # pass 2: load
    total, first = 0, True
    try:
        for chunk in pd.read_csv(path, dtype=str, chunksize=CSV_CHUNK, encoding=enc,
                                 keep_default_na=False, na_values=[""], low_memory=False):
            chunk = chunk.rename(columns=rename)
            for c in cols:
                n = rename[c]
                if numeric[c]:
                    chunk[n] = pd.to_numeric(chunk[n].str.replace(",", "", regex=False), errors="coerce")
                elif dates[c]:
                    chunk[n] = pd.to_datetime(chunk[n], errors="coerce", format="mixed")
            chunk.to_sql(table, eng, schema="dbo", if_exists="replace" if first else "append",
                         index=False, chunksize=SQL_CHUNK, dtype=dtype if first else None)
            first = False
            total += len(chunk)
            log.info("   ... %s: %d rows so far", table, total)
        record(eng, table, path, None, mtime, total, len(cols), "ok", f"encoding {enc}")
        log.info("   - %-55s %9d rows  %3d cols", table, total, len(cols))
        return [(table, total)]
    except Exception as e:
        record(eng, table, path, None, mtime, total, len(cols), "error", repr(e))
        log.error("   - %-55s ERROR %r", table, e)
        return []


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="reload every file")
    args = ap.parse_args()

    status = "FAILED"
    try:
        log.info("Python %s at %s", sys.version.split()[0], sys.executable)
        ensure_packages()
        eng = make_engines()
        if not MIS_ROOT.exists():
            raise SystemExit(f"MIS folder not found: {MIS_ROOT}")
        loaded, skipped, errors = 0, 0, 0
        for folder, prefix in FOLDERS.items():
            fdir = MIS_ROOT / folder
            log.info("== %s", fdir)
            for path in sorted(p for p in fdir.iterdir()
                               if p.is_file() and p.suffix.lower() in EXTENSIONS
                               and not p.name.startswith("~$")):
                mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)
                if not args.full and already_loaded(eng, path, mtime):
                    log.info(" %s  (unchanged, skipped)", path.name)
                    skipped += 1
                    continue
                log.info(" %s  (%.1f MB)", path.name, path.stat().st_size / 1048576)
                try:
                    res = (load_csv if path.suffix.lower() == ".csv" else load_excel)(
                        eng, path, prefix, mtime)
                    loaded += len(res)
                except Exception as e:
                    errors += 1
                    log.error("   could not read %s: %r", path.name, e)
        with eng.connect() as c:
            bad = c.exec_driver_sql("SELECT COUNT(*) FROM dbo._catalog WHERE status='error'").scalar()
        status = f"DONE  tables_loaded={loaded}  files_unchanged={skipped}  file_errors={errors}  catalog_errors={bad}"
        log.info(status)
    except SystemExit as e:
        status = f"FAILED  {e}"
        log.error(status)
    except Exception as e:
        status = f"FAILED  {e!r}"
        log.exception("Unexpected error")
    finally:
        STATUS_FILE.write_text(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {status}\nlog: {LOG_FILE}\n",
                               encoding="utf-8")


if __name__ == "__main__":
    main()
