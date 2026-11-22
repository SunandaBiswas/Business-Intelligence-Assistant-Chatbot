# <span style="color:#0A6B38">HR Assistant</span>
## <span style="color:#FFB800">System Architecture &amp; Deployment</span>

> A cloud-hosted business intelligence and knowledge assistant for Green Delta Insurance MIS registers and public annual reports.

<div align="center">

![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![Python](https://img.shields.io/badge/Backend-Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/Database-Supabase%20PostgreSQL-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white)
![Groq](https://img.shields.io/badge/AI-Groq%20LLM-F97316?style=for-the-badge)
![GitHub](https://img.shields.io/badge/Source-GitHub-181717?style=for-the-badge&logo=github&logoColor=white)

</div>

---

## 1. Architecture at a Glance

```mermaid
flowchart LR
    U["<b>Users</b><br/>Browser"]
    SC["<b>Streamlit Community Cloud</b><br/>app.py"]

    subgraph APP["<b>HR Assistant Application</b>"]
        PUB["<b>Public Chat</b><br/>Annual reports &amp; public website"]
        AUTH["<b>Authentication</b><br/>Sign in / Sign up / Approval"]
        CHAT["<b>MIS Chat</b><br/>Natural-language questions"]
        GLANCE["<b>At a Glance</b><br/>Register summaries"]
        SUMMARY["<b>Summary</b><br/>Trends and comparisons"]
        REPORT["<b>Excel Reports</b><br/>Tables and pivots"]
        ADMIN["<b>Admin</b><br/>Users and data status"]
    end

    ETL["<b>ETL Loader</b><br/>Excel / CSV -> PostgreSQL"]
    SRC["<b>Source Registers</b><br/>Excel and CSV files"]
    SB["<b>Supabase PostgreSQL</b><br/>MIS tables, catalog &amp; users"]
    GROQ["<b>Groq LLM API</b><br/>Text to SQL and explanations"]
    SK["<b>scikit-learn</b><br/>TF-IDF and cosine similarity"]
    REP["<b>Annual Reports</b><br/>PDF text and public website"]
    GH["<b>GitHub Repository</b><br/>Source and version history"]

    U --> SC
    GH -->|"Deployment branch"| SC
    SC --> AUTH
    SC --> PUB
    SC --> CHAT
    SC --> GLANCE
    SC --> SUMMARY
    SC --> REPORT
    SC --> ADMIN

    SRC -->|"Excel / CSV ingestion"| ETL
    ETL -->|"Create or refresh tables"| SB
    AUTH -->|"Account data"| SB
    CHAT -->|"Table names and schemas"| GROQ
    GROQ -->|"Read-only SQL"| CHAT
    CHAT -->|"Validated SQL"| SB
    SB -->|"Query results"| CHAT
    GLANCE --> SB
    SUMMARY --> SB
    REPORT --> SB
    ADMIN --> SB

    PUB --> REP
    PUB -->|"TF-IDF retrieval"| SK
    SK -->|"Relevant text chunks"| PUB
    PUB -->|"Question and context"| GROQ
    GROQ -->|"Public answer"| PUB

    style U fill:#DCEFE4,stroke:#0A6B38,stroke-width:2px
    style SC fill:#FFE59A,stroke:#FFB800,stroke-width:3px
    style APP fill:#F4F9F6,stroke:#0A6B38,stroke-width:2px
    style SB fill:#CFF1DF,stroke:#3FCF8E,stroke-width:3px
    style GROQ fill:#FFE2CC,stroke:#F97316,stroke-width:3px
    style GH fill:#E5E7EB,stroke:#181717,stroke-width:2px
    style SK fill:#E0F2FE,stroke:#0284C7,stroke-width:2px
    style REP fill:#FCE7F3,stroke:#DB2777,stroke-width:2px
```

---

## 2. Development Architecture

```mermaid
flowchart TD
    A["<b>Source Data</b><br/>Excel / CSV register workbooks"] --> B["<b>Data Preparation</b><br/>Pandas, header detection and type cleanup"]
    B --> C["<b>ETL Pipeline</b><br/>load_register.py"]
    C --> D["<b>Supabase Setup</b><br/>Catalog, helper functions and tables"]

    E["<b>Application Code</b><br/>Python modules and Streamlit pages"] --> F["<b>Authentication</b><br/>Email/password or optional Google sign-in"]
    E --> G["<b>Business Logic</b><br/>SQL agent, report and summary modules"]
    E --> H["<b>Knowledge Retrieval</b><br/>TF-IDF and public-source context"]

    D --> G
    F --> I["<b>Approved User Session</b>"]
    G --> J["<b>Interactive UI</b><br/>Chat, charts, tables and downloads"]
    H --> J
    I --> J

    J --> K["<b>Deployment Package</b><br/>requirements.txt + Streamlit secrets"]
    K --> L["<b>GitHub Repository</b>"]

    style A fill:#FFF3B0,stroke:#E5A800
    style B fill:#FFF3B0,stroke:#E5A800
    style C fill:#CFEFDB,stroke:#0A6B38
    style D fill:#CFEFDB,stroke:#0A6B38
    style E fill:#DDEAFE,stroke:#2563EB
    style F fill:#FCE7F3,stroke:#DB2777
    style G fill:#E0F2FE,stroke:#0284C7
    style H fill:#E9D5FF,stroke:#7C3AED
    style J fill:#DCEFE4,stroke:#0A6B38
    style K fill:#FFEDD5,stroke:#EA580C
    style L fill:#E5E7EB,stroke:#181717
```

### Core Development Components

| <span style="color:#0A6B38">Layer</span> | Responsibility | Main implementation |
|---|---|---|
| **Entry point** | Page navigation, branding, login state and application routing | `app.py` |
| **Presentation** | Chat, summaries, charts, Excel reports and administration screens | `app_pages/` |
| **Authentication** | Account creation, approval, access roles and password security | `auth.py` |
| **Database access** | Connection pooling, schema setup and safe identifiers | `db_connector.py` |
| **LLM SQL agent** | Table selection, SQL generation, correction and explanations | `sql_agent.py` |
| **Chat rendering** | Conversation history, result preview and Excel download | `chat_ui.py` |
| **Reporting** | Aggregations, pivots and formatted Excel workbooks | `report_data.py`, `excel_pivot.py`, `report_style.py` |
| **Knowledge retrieval** | Annual report chunks, TF-IDF ranking and public-source answers | `app_pages/public_chat.py` |
| **Data loading** | Excel/CSV discovery, cleaning and PostgreSQL loading | `etl/load_register.py` |

---

## 3. Data Flow

### 3.1 MIS Register and SQL Chat Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Streamlit Chat
    participant Agent as SQL Agent
    participant Groq as Groq LLM
    participant DB as Supabase PostgreSQL
    participant Excel as Excel Export

    User->>UI: Ask a MIS question
    UI->>Agent: Question + conversation history
    Agent->>DB: Read catalog and table schemas
    DB-->>Agent: Tables, columns and sample rows
    Agent->>Groq: Question + relevant schema
    Groq-->>Agent: Read-only SQL query
    Agent->>DB: Execute SELECT / WITH
    alt SQL succeeds
        DB-->>Agent: Result rows
    else SQL fails
        Agent->>Groq: SQL and database error
        Groq-->>Agent: Corrected SQL
        Agent->>DB: Retry once
    end
    Agent->>Groq: Question + result data
    Groq-->>Agent: Plain-language explanation
    Agent-->>UI: Answer, SQL, preview and limits
    UI->>Excel: Generate downloadable workbook
    Excel-->>User: BI report
```

### 3.2 Public Knowledge Chat Flow

```mermaid
sequenceDiagram
    autonumber
    actor Visitor
    participant Chat as Public Chat
    participant RAG as TF-IDF Retrieval
    participant Reports as Annual Report Text
    participant Web as Public GDIC Website
    participant Groq as Groq LLM

    Visitor->>Chat: Ask an annual report or public information question
    Chat->>Reports: Find local report text
    Chat->>RAG: Split text and rank relevant chunks
    RAG-->>Chat: Highest-similarity report sections
    Chat->>Web: Search public links when needed
    Web-->>Chat: Official public page text
    Chat->>Groq: Question + retrieved public context
    Groq-->>Chat: Context-grounded plain-language answer
    Chat-->>Visitor: Answer with public source URLs
```

---

## 4. Application Pages and Access

```mermaid
flowchart LR
    HOME["<b>Welcome</b>"] --> LOGIN["<b>Sign In / Sign Up</b>"]
    LOGIN --> PENDING["<b>Pending</b><br/>No private access"]
    LOGIN --> APPROVED["<b>Approved User</b>"]
    LOGIN --> ADMIN["<b>Administrator</b>"]

    PUBLIC["<b>Public Chat</b><br/>Available without login"]

    APPROVED --> CHAT["MIS Chat"]
    APPROVED --> GLANCE["At a Glance"]
    APPROVED --> SUMMARY["Summary"]
    APPROVED --> EXCEL["Excel Reports"]

    ADMIN --> CHAT
    ADMIN --> GLANCE
    ADMIN --> SUMMARY
    ADMIN --> EXCEL
    ADMIN --> USERS["Manage Users"]
    ADMIN --> STATUS["Data Status"]

    style PUBLIC fill:#DDEAFE,stroke:#2563EB,stroke-width:2px
    style PENDING fill:#FEF3C7,stroke:#D97706
    style APPROVED fill:#CFF1DF,stroke:#0A6B38
    style ADMIN fill:#FCE7F3,stroke:#DB2777
```

| Page | Access | Main purpose |
|---|---|---|
| Public Chat | Public | Answer questions using annual reports and public website content |
| Welcome | Public | Guide visitors to log in or wait for approval |
| MIS Chat | Approved / Administrator | Ask MIS questions in natural language and download results |
| At a Glance | Approved / Administrator | View register counts, date coverage and headline totals |
| Summary | Approved / Administrator | Compare year, month, week, class and customer measures |
| Excel Reports | Approved / Administrator | Create formatted reports and live or values-only pivots |
| Admin | Administrator | Approve, block or remove users and monitor data freshness |

---

## 5. Data Storage

```mermaid
erDiagram
    CATALOG ||--o{ REGISTER_TABLE : describes
    USERS {
        text email PK
        text name
        bytea pw_hash
        bytea salt
        text role
        text status
        timestamp created
    }
    CATALOG {
        text table_name PK
        text source_path
        text sheet_name
        timestamp file_mtime
        bigint row_count
        integer column_count
        text status
        text message
        timestamp loaded_at
    }
    REGISTER_TABLE {
        text columns
        numeric values
        text text_values
    }
```

### Database Responsibilities

- `_catalog` records source files, sheets, refresh time, row counts and loading status.
- `_users` stores account information, approved roles and access status.
- One or more public tables store the MIS register data.
- PostgreSQL helper functions support safe numeric conversions used by reporting logic.

---

## 6. Security and Reliability

<div style="padding:12px;border-left:5px solid #0A6B38;background:#EAF3ED;">

<strong>Application boundaries</strong>

- Public chat is isolated from private MIS and user data.
- Private pages require an approved account.
- The administrator alone can manage users and view the Admin page.
- SQL execution is intended to allow read-only `SELECT` and `WITH` queries.
- Query results are previewed, row-capped and exportable to Excel.
- Database passwords and API keys are read from environment variables or Streamlit secrets.
- `.env` and `.streamlit/secrets.toml` are excluded from source control.

</div>

Additional reliability features include:

- SQLAlchemy pool pre-ping and connection recycling.
- Supabase SSL connections.
- Automatic LLM SQL correction after one failed database query.
- Streamlit session history limited to recent messages.
- ETL skipping for unchanged source files.
- Catalog synchronization and data freshness monitoring.

---

## 7. Deployment Architecture

```mermaid
flowchart LR
    DEV["<b>Developer</b><br/>Local source code"] -->|"git push"| GH["<b>GitHub</b><br/>main branch"]
    GH -->|"Automatic deploy"| ST["<b>Streamlit Community Cloud</b><br/>Python runtime"]

    ST -->|"App dependencies"| REQ["<b>requirements.txt</b><br/>Python packages"]
    ST -->|"Encrypted hosting settings"| SEC["<b>Streamlit Secrets</b><br/>Groq, Supabase and Admin"]

    SEC --> GROQ["<b>Groq API</b>"]
    SEC --> DB["<b>Supabase PostgreSQL</b>"]
    ST --> USERS["<b>End Users</b><br/>Desktop and mobile browsers"]

    USERS -->|"HTTPS"| ST
    ST -->|"HTTPS / PostgreSQL SSL"| DB
    ST -->|"API request"| GROQ

    style DEV fill:#DCEFE4,stroke:#0A6B38
    style GH fill:#E5E7EB,stroke:#181717
    style ST fill:#FFE59A,stroke:#FFB800,stroke-width:3px
    style SEC fill:#FCE7F3,stroke:#DB2777
    style DB fill:#CFF1DF,stroke:#3FCF8E
    style GROQ fill:#FFE2CC,stroke:#F97316
```

### Deployment Sequence

1. Develop and test locally with `streamlit run app.py`.
2. Push source code to GitHub.
3. Configure Streamlit Community Cloud with:
   - Repository: `projectdata2698-ship-it/HR-Assistant`
   - Branch: `main`
   - Entry file: `app.py`
   - Python: 3.12 or 3.13
4. Add Groq, Supabase, administrator and optional Google OAuth values to Streamlit secrets.
5. Streamlit installs `requirements.txt`.
6. Streamlit loads `app.py` and connects to Supabase and Groq.
7. End users access the application over HTTPS.
8. New sign-ups remain pending until an administrator approves them.

---

## 8. Technology Stack

| Area | Technology | Purpose |
|---|---|---|
| Frontend / UI | Streamlit | Multi-page web interface, chat and downloads |
| Application language | Python | Business logic, ETL and integrations |
| Primary database | Supabase PostgreSQL | MIS data, catalog and user accounts |
| Database library | SQLAlchemy + psycopg | Connection pooling and parameter-safe SQL |
| AI service | Groq LLM | Table routing, SQL generation and answer synthesis |
| Text retrieval | scikit-learn TF-IDF | Annual report chunk ranking |
| Document text | pypdf | PDF text extraction support |
| Data processing | pandas | Data cleaning and tabular results |
| Excel generation | openpyxl / pandas | Downloadable reports and formatted workbooks |
| Authentication | Streamlit Auth / Authlib | Email/password and optional Google sign-in |
| Hosting | Streamlit Community Cloud | Managed application deployment |
| Source control | GitHub | Version control and deployment trigger |

---

## 9. Architecture Summary

```mermaid
mindmap
  root((HR Assistant))
    Development
      Python
      Streamlit pages
      Pandas
      ETL scripts
    Data
      Supabase PostgreSQL
      MIS register tables
      Catalog metadata
      User accounts
    AI
      Groq LLM
      Natural-language SQL
      TF-IDF retrieval
      Cosine similarity
    Business Features
      MIS Chat
      At a Glance
      Summary
      Excel Reports
      Public Chat
      Admin
    Operations
      GitHub
      Streamlit Community Cloud
      Streamlit secrets
      Supabase SSL
```

<div align="center">

### <span style="color:#0A6B38">Development</span>
<b>Python + Streamlit + Pandas</b>

↓

### <span style="color:#2563EB">Knowledge and Data</span>
<b>Groq LLM + TF-IDF + Supabase PostgreSQL</b>

↓

### <span style="color:#FFB800">Deployment</span>
<b>GitHub + Streamlit Community Cloud</b>

↓

### <span style="color:#DB2777">Users</span>
<b>Public Visitors + Approved Staff + Administrator</b>

</div>
