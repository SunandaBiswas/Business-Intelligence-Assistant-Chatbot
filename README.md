# Business Intelligence Assistant Chatbot

A Streamlit web app that lets people at **Green Delta Insurance (GDIC)** ask questions about their MIS
registers (collection, renewal, claims, targets, bancassurance, employee lists …) **in plain English**,
and get back an answer, the SQL that produced it, the data, and a ready-to-download **Excel report**.

> Instead of asking an analyst to write a query or build a pivot table, you type
> *"Which 10 branches had the highest claim payments?"* and the app does the rest.

---

## 1. What is this web app about?

Insurance MIS teams keep their data in large Excel registers (Collection Register, Claim Register,
Renewal Register, Targets …). Answering even a simple question normally means opening a huge workbook,
filtering, building a pivot table and formatting the result before sending it to a manager.

This project removes that manual work:

1. The registers are loaded once into a cloud **PostgreSQL database (Supabase)** by an ETL script.
2. A **Streamlit** web app sits on top of the database.
3. An **LLM (Groq)** translates the user's question into a read-only SQL query, runs it safely,
   and explains the result in plain language.
4. The user can export the result, or generate **department-style Excel reports and pivots**
   (with real Excel formulas if wanted) in a couple of clicks.
5. Access is controlled: the **Chat** page is public, everything else needs an account that the
   **administrator approves**.

### Who is it for?
| User | What they do with it |
|------|----------------------|
| Business / MIS staff | Ask questions in English, download results as Excel |
| Managers & clients | Look at the *At a glance* tiles and *Summary* charts for a quick business picture |
| Report builders | Generate formatted department reports and pivots without touching Excel |
| Administrator | Approve / block users, check data freshness and system status |

---

## 2. Features

| Page | Access | What it does |
|------|--------|--------------|
| **Chat** | Public | Ask a question in plain English, or paste a `SELECT` query. Shows the answer, the SQL used, a data preview and an Excel download. Remembers the last few messages so follow-ups work. |
| **At a glance** | Approved users | One summary tile per register: row count, date coverage, headline total (premium / amount paid / target), and when the file was last updated. Each tile has an **Ask** pop-up with suggested questions for that register type. |
| **Summary** | Approved users | Year-wise, month-wise, week-wise, class-wise and customer-wise premium, compared side by side across the registers you select, with stacked bar charts. Filter by date range, customer or class. |
| **Excel reports** | Approved users | *Department report* (title bar, bordered table, Grand Total row/column) and a *Pivot generator*. Output as **values only**, **totals as formulas**, or **full live formulas** (`SUMIFS`, `COUNTIFS` …) over a data sheet. Several colour palettes. |
| **Admin** | Administrator only | Approve / block / delete users, change roles and passwords, view data status, re-sync the table catalog, and see system info. |

Other highlights:
* **Safe by design** – only `SELECT` / `WITH` queries are executed; results are row-capped and have a timeout; nothing is ever committed.
* **Self-correcting** – if the generated SQL fails, the error is fed back to the LLM for one automatic retry.
* **Login options** – email + password (salted scrypt hash, never plain text) and optional Google sign-in.
* **Branded UI** – Green Delta green/yellow theme configured in `.streamlit/config.toml`.

---

## 3. How a question is answered (architecture)

```
 User question
      │
      ▼
 ┌────────────┐  1. pick_tables()   LLM chooses the 1–3 most relevant tables
 │ sql_agent  │  2. table_schema()  columns, types and 3 sample rows of those tables
 │   .py      │  3. generate_sql()  LLM writes ONE read-only SQL query
 │            │  4. validate_sql()  only SELECT / WITH allowed
 │            │  5. run_query()     row cap + timeout, never commits
 │            │  6. summarize()     LLM explains the result in plain language
 └─────┬──────┘
       │ (error? → regenerate SQL once with the error message)
       ▼
 answer + SQL + data table + Excel download      ◄── rendered by chat_ui.py
       ▲
       │ reads from
 ┌─────┴──────────────┐          ┌──────────────────────────┐
 │ Supabase PostgreSQL │ ◄─────── │ etl/ scripts load Excel  │
 │ (registers+_users)  │          │ registers into tables    │
 └─────────────────────┘          └──────────────────────────┘
```

**Tech stack:** Python · Streamlit · SQLAlchemy + psycopg · Supabase (PostgreSQL) · Groq LLM API
(default model `openai/gpt-oss-120b`) · pandas · openpyxl · Authlib (Google sign-in).

---

## 4. Project structure – what each part does

```
.
├── app.py                    Entry point. Page navigation, sidebar branding, login gating, DB status.
├── app_pages/                One file per page of the web app
│   ├── chat.py                 Chat with the registers (public)
│   ├── glance.py               "At a glance" tiles + Ask pop-up
│   ├── summary.py              Year / class / customer comparison + charts
│   ├── excel_reports.py        Department reports + pivot generator + downloads
│   └── admin.py                User approval, data & system tabs (admin only)
│
├── sql_agent.py              Text-to-SQL engine: table picking, SQL generation, validation,
│                             execution, summarising, Excel export, chat history formatting.
├── chat_ui.py                Renders a chat message and runs one chat turn (shared by Chat and tile pop-ups).
├── suggestions.py            Suggested questions per register type (Collection, Renewal, Claims …).
│
├── glance_data.py            Data layer for "At a glance": per-register stats read from the catalog.
├── summary_data.py           Data layer for "Summary": premium by year / month / week / class / customer.
├── report_data.py            Data access for Excel reports & pivots (builds a "pivot spec" and aggregates).
├── excel_pivot.py            Builds the formatted .xlsx (values / totals-as-formulas / full formulas).
├── report_style.py           Colour palettes for the Excel reports and their on-screen preview.
│
├── auth.py                   Sign up / log in / Google sign-in, roles and approval status
│                             (approved / pending / blocked), stored in Supabase table `_users`.
├── db_connector.py           SQLAlchemy engine for Supabase, identifier quoting, catalog sync, helper SQL functions.
├── common.py                 Shared cached engine + database health check.
│
├── etl/                      Getting data INTO the database (not needed to just run the app)
│   ├── load_register.py        Loads Excel/CSV registers into Supabase (skips unchanged files; `--full` to force).
│   ├── run_load_register.bat   Windows Task Scheduler wrapper for a daily load.
│   ├── migrate_sqlserver_to_supabase.py   One-off copy of the old local SQL Server database to Supabase.
│   └── load_register_simple.py Original, simpler SQL Server loader (kept for reference).
├── sql/create_mis_databases.sql   Early SQL Server script that created one database per MIS folder.
├── Excel/                    Sample register workbooks (Claim, Collection, Employee List).
├── rag.ipynb / rag.py        Early RAG experiment (notebook); not used by the app.
│
├── assets/                   GDIC logo and icon.
├── .streamlit/
│   ├── config.toml             Theme (Green Delta green + yellow).
│   └── secrets.toml.example    Template for keys / DB URL / Google login. Copy to secrets.toml.
├── requirements.txt          What the hosted app needs.
├── requirements-etl.txt      Extra packages for the ETL scripts.
├── requirements-full.txt     Everything, including notebooks / experiments.
└── DEPLOY.md                 Step-by-step guide to host on Streamlit Community Cloud.
```

---

## 5. Getting started (run locally)

### Prerequisites
* Python 3.12 or 3.13
* A [Groq](https://console.groq.com) API key
* A [Supabase](https://supabase.com) project (use the **Session pooler** connection string)

### Steps
```bash
# 1. clone
git clone https://github.com/SunandaBiswas/Business-Intelligence-Assistant-Chatbot.git
cd Business-Intelligence-Assistant-Chatbot

# 2. virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)

# 3. install
pip install -r requirements.txt

# 4. configure secrets
copy .streamlit\secrets.toml.example .streamlit\secrets.toml     # then edit it
#   GROQ_API_KEY, SUPABASE_DB_URL (URL-encode the password), ADMIN_PASSWORD
#   Alternatively put the same keys in a .env file.

# 5. run
streamlit run app.py
```

Check the database connection on its own with `python db_connector.py`.

### Configuration reference
| Key | Purpose |
|-----|---------|
| `GROQ_API_KEY` | Groq API key used for the LLM |
| `GROQ_MODEL` | Optional – override the default model |
| `SUPABASE_DB_URL` | PostgreSQL connection string (Supabase session pooler) |
| `ADMIN_PASSWORD` | Used once, when the administrator account is first created |
| `[auth]` / `[auth.google]` | Optional Google sign-in (client id / secret / redirect URI) |

`.env` and `.streamlit/secrets.toml` are git-ignored – **never commit real keys.**

---

## 6. Loading data into the database

```bash
pip install -r requirements-etl.txt
python etl/load_register.py          # incremental: only files that changed since the last load
python etl/load_register.py --full   # reload everything
```
* One table per file (or per sheet for multi-sheet workbooks).
* Every table is listed in `public._catalog` with its source, row count and status; the app reads this
  catalog to know what data exists.
* `etl/run_load_register.bat` can be scheduled with Windows Task Scheduler for a daily refresh.
* The source folder path in `load_register.py` points to the company OneDrive/SharePoint MIS folder –
  change `MIS_ROOT` to wherever your Excel files live.

---

## 7. Users, approval and security

1. A visitor signs up (email + password, or Google). The account starts as **pending**.
2. The administrator opens **Admin → Users → Waiting for approval** and approves it.
3. Approved users unlock *At a glance*, *Summary* and *Excel reports*; pending or blocked users see only Chat.

Security measures: salted **scrypt** password hashes, read-only SQL enforcement, query timeout and row cap,
secrets kept out of Git. Before sharing a public link, rotate any key or password that has ever been pasted
into a chat or document.

---

## 8. Deployment

The app is designed for **Streamlit Community Cloud**: push to GitHub, create the app with `app.py` as the
main file, paste the secrets in *Advanced settings*. Full instructions, including Google sign-in setup, are in
[DEPLOY.md](DEPLOY.md).

---

## 9. Example questions to try

* How many rows are in the collection register?
* Total premium collected by year from the collection register
* Which 10 branches had the highest claim payments?
* Show the target by distribution channel for 2023
* Premium by class of business for the latest year

---

## 10. Author

**Sunanda Biswas** – built for Green Delta Insurance's MIS team.
