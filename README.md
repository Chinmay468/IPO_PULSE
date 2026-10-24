# IPO Pulse & Wealth Intelligence Platform

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com)
[![Tests](https://img.shields.io/badge/Tests-193%20Passed-success?style=for-the-badge&logo=pytest&logoColor=white)](https://pytest.org)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

An asynchronous, full-stack financial intelligence and wealth management system engineered with **FastAPI**, **SQLAlchemy 2.0 (`asyncpg` / `aiosqlite`)**, **Pydantic v2**, **APScheduler**, and a responsive fintech Single Page Application (SPA).

The platform tracks Indian Primary Markets (Mainboard & SME IPOs), executes multi-factor algorithmic scoring (0–100), proxies real-time registrar allotments, integrates live broker sync via **Angel One SmartAPI**, tracks Mutual Fund folios with Consolidated Account Statement (CAS) parsing & exact **Newton-Raphson XIRR**, runs technical swing analyses (Wilder's RSI, EMAs, ATR trailing stops), provides context-aware **AI Copilot** portfolio diagnostics (Gemini & Groq failover), and dispatches automated **Telegram Bot** alerts.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph External_Feeds ["External Feeds & Market Sources"]
        Chittorgarh["Chittorgarh Scraper\n(Mainboard, SME, GMP, Subscriptions)"]
        YahooFinance["Yahoo Finance\n(Quotes & 1-Year OHLCV)"]
        AMFI["AMFI India API\n(Mutual Fund Daily NAVs)"]
        LinkIntime["Link Intime Portal\n(Registrar Allotment Proxy)"]
        AngelOneAPI["Angel One SmartAPI\n(Broker Portfolio & TOTP)"]
    end

    subgraph Backend_Core ["FastAPI Core Services (Python 3.12)"]
        ScraperSvc["Scraper & Discovery Service"]
        MarketPriceSvc["Market Price & Ticker Cache"]
        ScoringEngine["4-Pillar Scoring Engine (0-100)"]
        TechAnalysisSvc["Technical Analysis Engine\n(RSI, EMA, ATR, Ratchet Stop)"]
        MFSvc["Mutual Fund Engine\n(CAS Parser & Newton-Raphson XIRR)"]
        RegistrarProxy["Registrar Proxy"]
        AICopilot["AI Portfolio Doctor\n(Gemini / Groq Multi-Key Pool)"]
        TelegramSvc["Telegram Bot & Webhook Service"]
        Scheduler["APScheduler Daemon\n(15m Scrapes, 00:05 IST Corrections)"]
    end

    subgraph Data_Layer ["Persistence & Cache"]
        Postgres[(PostgreSQL 16\nSQLAlchemy 2.0 Async)]
        Alembic["Alembic Migrations\n(10 Schema Versions)"]
        PriceCache["In-Memory TTL Quote Cache"]
    end

    subgraph Presentation_Layer ["Presentation & Ingress"]
        Caddy["Caddy v2 Reverse Proxy\n(Auto Let's Encrypt SSL)"]
        SPA["Vanilla JS Fintech SPA\n(Tailwind CSS, Lucide, Chart.js)"]
        TelegramUser["Telegram Client\n(Push Alerts & Interactive Commands)"]
    end

    Chittorgarh --> ScraperSvc
    YahooFinance --> MarketPriceSvc
    AMFI --> MFSvc
    LinkIntime --> RegistrarProxy
    AngelOneAPI --> Backend_Core

    ScraperSvc --> ScoringEngine
    MarketPriceSvc --> TechAnalysisSvc
    TechAnalysisSvc --> AICopilot
    Backend_Core --> Postgres
    Alembic -.-> Postgres
    MarketPriceSvc -.-> PriceCache

    Scheduler --> ScraperSvc
    Scheduler --> MFSvc
    ScoringEngine --> TelegramSvc

    SPA <--> Caddy
    Caddy <--> Backend_Core
    TelegramSvc <--> TelegramUser
```

---

## Core Capabilities

### 1. IPO Intelligence & Discovery Engine
* **Comprehensive Tracking**: Synchronizes Mainboard and SME IPOs from Chittorgarh and market sources.
* **Resilient Discovery Scraper**: Respects `robots.txt`, implements polite 2–3s request jitter, in-memory caching, and detects upcoming/DRHP-filed issues.
* **Deterministic IST Date Status Correction**: Enforces Indian Standard Time (IST) calendar rules. Issues are marked `UPCOMING` before open date, `LIVE` during bidding (until 5:00 PM IST on close date), `CLOSED` upon closing, and `LISTED` after the listing date. Handles issues with unannounced dates via a `dates_tba` flag.
* **Seed Data Isolation**: Seed data (`is_seed`) is completely isolated from live production analytics and user-facing cards.
* **Live GMP & Subscription Multiple Ingestion**: Tracks institutional (QIB), non-institutional (NII/HNI), and retail subscription demand alongside Grey Market Premium trends.
* **Direct Broker Deep-Links**: One-click apply redirects (`HTTP 307`) to Angel One's live bidding portal.

### 2. Multi-Pillar Composite Scoring Model (0–100)
A quantitative model that evaluates IPOs across four dimensions, assigning an actionable rating: **`STRONG APPLY`**, **`APPLY`**, **`NEUTRAL`**, or **`AVOID`**.

| Dimension | Weight | Evaluation Criteria |
| :--- | :---: | :--- |
| **Grey Market Premium (GMP)** | **35 pts** | Percentage gain over issue price. $\ge 50\%$ gets 35 pts; $30-50\%$ gets $28-35$ pts; $15-30\%$ gets $18-28$ pts; $<0\%$ gets 0 pts. |
| **Subscription Demand** | **30 pts** | Institutional backing (QIB up to 16 pts), Retail participation (up to 6 pts), and Total oversubscription (up to 8 pts). |
| **Valuation & Fundamentals** | **20 pts** | IPO P/E compared to Industry Average P/E (discount vs premium, up to 12 pts) and Return on Net Worth (RoNW %, up to 8 pts). |
| **Issue Structure & Size** | **15 pts** | Fresh issue ratio (growth capital vs promoter OFS cashing out, up to 10 pts) and market liquidity comfort (up to 5 pts). |

* **Rating Thresholds**:
  * **`STRONG APPLY`**: Score $\ge 75.0$
  * **`APPLY`**: $60.0 \le \text{Score} < 75.0$
  * **`NEUTRAL`**: $45.0 \le \text{Score} < 60.0$
  * **`AVOID`**: $\text{Score} < 45.0$
* **Explainable Insights**: Automatically generates positive catalysts and risk warnings for every issue.

### 3. Stock Portfolio & Technical Advisory Engine
* **Angel One SmartAPI Live Sync**: Direct broker connection authenticating via Client ID, MPIN, API Key, and automated TOTP generation using `pyotp`.
* **Multi-Broker CSV/Excel Import**: Robust parser supporting exports from **Zerodha (Console / Kite)**, **Groww**, **Angel One**, and **Upstox**.
* **Real-time Price Feeds**: Ticker data and 1-year OHLCV candles via Yahoo Finance (`yfinance`) with TTL caching and graceful fallbacks.
* **Quantitative Technical Diagnoses**:
  * **Wilder's Smoothed RSI (14)**: Oversold/overbought momentum detection.
  * **Exponential Moving Averages (EMA 20, 50, 200)**: Trend alignment and golden/death cross tracking.
  * **Average True Range (ATR)**: Volatility-based risk sizing.
  * **Ratcheting Trailing Stop-Loss**: Protects capital as profits accrue.
  * **Swing High Targets**: Evaluates 1st and 2nd reward-to-risk targets (2:1 minimum baseline).
* **Systematic Swing Suggestions**: Logs actionable trading setups and tracks historical hit rates via a dedicated scorecard.

### 4. Mutual Funds & Consolidated Account Statement (CAS) Engine
* **Automated CAS Parsing**: Ingests CAMS and KFintech CAS statements in PDF and password-protected Excel formats (`casparser`, `msoffcrypto-tool`).
* **Daily AMFI NAV Ingestion**: Automatic synchronization with official AMFI (Association of Mutual Funds in India) feeds with local caching.
* **Exact Newton-Raphson XIRR**: Computes exact annualized returns across irregular cashflows, SIP instalments, and lump-sum redemptions.
* **Portfolio Analytics**: Folio masking, category allocation (Equity, Debt, Hybrid, Solution Oriented), and capital gains estimation (LTCG / STCG).
* **Unified Net Worth Strip**: Merges equity holdings with mutual fund valuations into an adaptive combined net worth display.

### 5. Registrar Allotment Status Proxy
* **Link Intime Real-Time Querying**: Direct proxy querying allotment status via PAN, Application Number, or DP ID / Client ID.
* **Standardized Status Normalization**: Normalizes varied registrar responses into uniform states: `ALLOTTED`, `NOT_ALLOTTED`, `NOT_FOUND`, or `PENDING`.

### 6. AI Portfolio Doctor & Conversational Copilot
* **Dual-LLM Engine with Key Pooling**: Primary integration with Google Gemini (`gemini-3.1-flash-lite`) and Groq (`openai/gpt-oss-120b`), backed by multi-key rotation and smart failover.
* **Context-Aware Portfolio Analysis**: Analyzes concentrated holdings, drawdown risk, tax implications, and provides concrete turnaround advice.
* **Web-Search Grounding**: Live search integration (`duckduckgo_search`) to ground recommendations in recent corporate actions and earnings results.
* **Voice Read-Aloud**: Audio synthesizer integration for hands-free audio briefing in the frontend floating dock.

### 7. Automated Telegram Bot & Webhooks
* **Proactive Alerts**: Instantly notifies on high-conviction IPOs exceeding score and GMP thresholds (with SME filter options).
* **Top Picks Daily Digest**: Automated morning summary sent to channels or private chats.
* **Interactive Bot Commands**:
  * `/start` - Bot status, active settings, and command reference.
  * `/shares` - Instant swing trade recommendations with entry, stop-loss, and targets.
  * `/scorecard` - Historical performance metrics of swing suggestions.
  * `/suggest <IPO>` - Instant on-demand evaluation of any tracked IPO.
* **Security & Privacy**: Built-in log sanitization masking sensitive tokens and API keys.

---

## Directory Structure

```
Enquirer Service/
├── app/
│   ├── main.py                     # Application entry point, lifespan, CORS, router mounting
│   ├── config.py                   # Pydantic v2 application settings & environment schema
│   ├── database.py                 # Async SQLAlchemy 2.0 engine, async session factory, init_db
│   ├── auth.py                     # JWT token generator, password hashing, and SlowAPI rate limiter
│   ├── rate_limiter.py             # Global IP-based rate limiting configurations
│   ├── models/
│   │   ├── ipo.py                  # Models: IPO, IPOSubscription, IPOGmp, IPOScore, IPODocument, etc.
│   │   ├── portfolio.py            # Models: Holding, Transaction, SuggestionLog, TechnicalDiagnosis
│   │   ├── mutual_fund.py          # Models: MFScheme, MFHolding, MFTransaction, MFNavHistory
│   │   └── prediction.py           # Models: Prediction, PredictionResult
│   ├── schemas/
│   │   ├── ipo.py                  # Pydantic schemas for IPO catalog, GMP, subscriptions, scoring
│   │   ├── portfolio.py            # Pydantic schemas for equity holdings, broker sync, technicals
│   │   └── mutual_fund.py          # Pydantic schemas for CAS import, folios, NAVs, XIRR
│   ├── services/
│   │   ├── ipo_service.py          # Business logic for IPO filtering, sorting, and details
│   │   ├── scoring_service.py      # 4-pillar algorithmic scoring & recommendation logic
│   │   ├── scraper_service.py      # Background scraper, GMP & subscription syncing, data seeding
│   │   ├── chittorgarh_scraper.py  # Chittorgarh table parser, upcoming discovery, and DRHP fetcher
│   │   ├── registrar_proxy.py      # Link Intime registrar allotment query proxy
│   │   ├── scheduler.py            # APScheduler daemon (15m market sync, 00:05 IST status job)
│   │   ├── angelone_sync_service.py# Angel One SmartAPI integration with TOTP authentication
│   │   ├── csv_import_service.py   # Multi-broker CSV/Excel holdings parser (Zerodha, Groww, etc.)
│   │   ├── market_price_service.py # Yahoo Finance live quote and OHLCV candle fetcher with cache
│   │   ├── technical_analysis_service.py # RSI, EMA, ATR, ratcheting stops, and target projections
│   │   ├── mutual_fund_service.py  # Mutual fund portfolio aggregation and allocation engine
│   │   ├── mf_cas_parser_service.py# CAMS / KFintech CAS PDF & Excel file parser
│   │   ├── mf_nav_service.py       # AMFI official daily NAV feed synchronizer
│   │   ├── xirr_service.py         # Exact Newton-Raphson XIRR implementation
│   │   ├── portfolio_service.py    # Portfolio summary, health calculation, and snapshot tracking
│   │   ├── portfolio_advisor_service.py # Portfolio diagnosis and Copilot reasoning engine
│   │   ├── gemini_client_service.py# Google Gemini LLM client with multi-key pooling
│   │   ├── groq_client_service.py  # Groq LLM client with fallback orchestration
│   │   ├── key_pool_base.py        # Generic thread-safe API key pool manager
│   │   ├── web_search_service.py   # Web search grounding for live financial context
│   │   ├── telegram_service.py     # Telegram bot dispatch, webhook handler, alert generator
│   │   ├── prediction_service.py   # ML listing-day price prediction model
│   │   └── company_facts_service.py# Fundamental financial facts and ratios retriever
│   ├── routers/
│   │   ├── auth.py                 # /api/v1/auth (Login, JWT token issue)
│   │   ├── ipo.py                  # /api/v1/ipos (CRUD, filters, GMP, subscriptions, Angel One link)
│   │   ├── allotment.py            # /api/v1/allotment (Link Intime companies & allotment checks)
│   │   ├── portfolio.py            # /api/v1/portfolio (Holdings, Angel One import, CSV, Copilot chat)
│   │   ├── mutual_fund.py          # /api/v1/mf (CAS import, NAV sync, summary, XIRR)
│   │   ├── scoring.py              # /api/v1/scoring (Scoring rules, what-if calculator, track record)
│   │   ├── scraper.py              # /api/v1/scraper (Sync triggers, seed data, status)
│   │   ├── telegram.py             # /api/v1/telegram (Webhooks, alerts, test broadcasts, digest)
│   │   └── predictions.py          # /api/v1/predictions (Listing day price model evaluation)
│   └── static/
│       ├── index.html              # Responsive single-page application dashboard
│       ├── css/styles.css          # Custom styling and animations
│       └── js/
│           ├── app.js              # Tab controller, live sync daemon (15s), bootstrap logic
│           ├── auth.js             # Client-side authentication token handling
│           ├── charts.js           # Chart.js asset allocation & portfolio performance renderers
│           ├── ipos.js             # IPO cards, live counters, modals, GMP/subscription UI
│           ├── portfolio.js        # Stock portfolio cards, P&L, Angel One modal, CSV upload
│           ├── mutual_funds.js     # MF summary, CAS import modal, XIRR calculations
│           ├── technical_advisory.js # Technical diagnosis pills, swing setups, scorecard
│           └── utils.js            # Formatters (INR currency, dates, sanitizers)
├── alembic/
│   ├── env.py                      # Alembic async migration environment
│   └── versions/                   # Migration versions (001 to 010)
├── tests/                          # Automated test suite (193 tests)
├── docker-compose.yml              # Container definitions (PostgreSQL 16, App, Caddy)
├── Dockerfile                      # Production container image definition
├── entrypoint.py                   # Container initialization, DB readiness check & migrations
├── Caddyfile                       # Caddy reverse proxy configuration with automatic HTTPS
├── requirements.txt                # Production dependencies
├── pyproject.toml                  # Project metadata and tooling config
└── .env.example                    # Environment configuration template
```

---

## Complete API Reference

All application endpoints are versioned under the `/api/v1` prefix. Interactive API documentation is accessible at `/docs` (Swagger UI) and `/redoc` (ReDoc).

### 1. Authentication (`/api/v1/auth`)
* `POST /api/v1/auth/login` — Authenticate single-user admin credentials and receive a JWT Bearer token. Rate limited to 5 requests/min.

### 2. IPO Management & Discovery (`/api/v1/ipos`)
* `GET /api/v1/ipos` — List all IPOs with filtering options (`status`, `ipo_type`, `recommendation`, `min_score`, `search`, `skip`, `limit`).
* `GET /api/v1/ipos/{id}` — Retrieve complete IPO profile, subscription history, GMP snapshots, and score rationale.
* `GET /api/v1/ipos/symbol/{symbol}` — Query IPO by ticker symbol.
* `POST /api/v1/ipos` — Create an IPO master entry *(Auth required)*.
* `PUT /api/v1/ipos/{id}` — Update IPO attributes *(Auth required)*.
* `DELETE /api/v1/ipos/{id}` — Delete an IPO record *(Auth required)*.
* `POST /api/v1/ipos/{id}/subscriptions` — Append a subscription snapshot (`qib`, `nii`, `retail`, `total`) *(Auth required)*.
* `POST /api/v1/ipos/{id}/gmp` — Append a GMP update (`gmp_amount`, `gmp_percentage`) *(Auth required)*.
* `GET /api/v1/ipos/{id}/score` — Retrieve composite score and pillar breakdowns.
* `POST /api/v1/ipos/{id}/score/recalculate` — Recalculate composite score on-demand *(Auth required)*.
* `GET /api/v1/ipos/{id}/score/breakdown` — Detailed quantitative scoring factors and penalty analysis.
* `GET /api/v1/ipos/{id}/apply/angelone` — Direct `HTTP 307` redirect to Angel One bidding portal by IPO ID.
* `GET /api/v1/ipos/symbol/{symbol}/apply/angelone` — Direct `HTTP 307` redirect to Angel One by ticker symbol.

### 3. Registrar Allotment Status (`/api/v1/allotment`)
* `GET /api/v1/allotment/linkintime/companies` — Fetch current list of IPOs available on Link Intime.
* `POST /api/v1/allotment/linkintime/check` — Query allotment status by `PAN`, `APP_NO`, or `DPID`. Rate limited to 30 requests/min.

### 4. Stock Portfolio & Advisory (`/api/v1/portfolio`)
* `GET /api/v1/portfolio/summary` — Overview of invested capital, current valuation, and total P&L.
* `GET /api/v1/portfolio/net-worth` — Combined net worth integrating Stocks and Mutual Funds.
* `GET /api/v1/portfolio/holdings` — List all stock holdings with live Yahoo Finance prices and P&L.
* `POST /api/v1/portfolio/holdings` — Manually add a stock holding *(Auth required)*.
* `DELETE /api/v1/portfolio/holdings/{id}` — Remove a stock holding *(Auth required)*.
* `GET /api/v1/portfolio/holdings/{symbol}/history` — Historical price and holding valuation chart data.
* `GET /api/v1/portfolio/snapshots` — Periodic net worth performance history snapshots.
* `POST /api/v1/portfolio/holdings/{id}/transactions` — Record buy/sell transaction for a holding.
* `POST /api/v1/portfolio/import/csv` — Upload holdings CSV/Excel from Zerodha, Groww, Angel One, or Upstox.
* `GET /api/v1/portfolio/import/angelone/status` — Inspect Angel One broker connection status.
* `POST /api/v1/portfolio/import/angelone` — Sync live holdings from Angel One SmartAPI using TOTP.
* `GET /api/v1/portfolio/advisory` — Quantitative portfolio health audit and risk distribution.
* `POST /api/v1/portfolio/advisory/ask` — Conversational AI Copilot chat query grounded in portfolio context.
* `GET /api/v1/portfolio/scorecard` — Performance tracking and win-rate metrics for swing trade setups.
* `GET /api/v1/portfolio/technical-scorecard` — Aggregate accuracy of technical diagnoses.

### 5. Mutual Funds Module (`/api/v1/mf`)
* `POST /api/v1/mf/import/cas` — Parse and import CAMS / KFintech CAS PDF or Excel statement.
* `GET /api/v1/mf/summary` — Mutual fund aggregate valuation, total gain/loss, category breakdown, and portfolio XIRR.
* `GET /api/v1/mf/{scheme_id}/history` — Historical NAV performance for a specific scheme.
* `POST /api/v1/mf/sync-navs` — Fetch latest daily NAVs from AMFI India.
* `POST /api/v1/mf/holdings` — Manually add a mutual fund holding.
* `PUT /api/v1/mf/holdings/{holding_id}` — Update mutual fund holding details.
* `DELETE /api/v1/mf/holdings/{holding_id}` — Delete a mutual fund holding.
* `POST /api/v1/mf/holdings/{holding_id}/transactions` — Add a SIP or lump-sum transaction.
* `DELETE /api/v1/mf/transactions/{transaction_id}` — Delete a mutual fund transaction.

### 6. Scoring Methodology & Track Record (`/api/v1/scoring`)
* `GET /api/v1/scoring/rules` — View canonical weights, thresholds, and mathematical interpolation logic.
* `POST /api/v1/scoring/calculate` — Interactive what-if scoring calculator.
* `GET /api/v1/scoring/track-record` — Historical listing-day gain accuracy grouped by recommendation tier.

### 7. Scraper & Scheduler Controls (`/api/v1/scraper`)
* `POST /api/v1/scraper/sync` — Trigger immediate market sync and score recalculation *(Auth required)*.
* `POST /api/v1/scraper/sync-details` — Trigger detailed Chittorgarh page scrape *(Auth required)*.
* `POST /api/v1/scraper/seed` — Seed initial baseline IPO data *(Auth required, requires `ALLOW_SEED=1`)*.
* `GET /api/v1/scraper/status` — View scheduler heartbeat, next run times, and sync freshness.

### 8. Telegram Bot & Webhooks (`/api/v1/telegram`)
* `GET /api/v1/telegram/status` — Connection status, chat ID, and active notification filters.
* `POST /api/v1/telegram/test` — Dispatch a test notification.
* `POST /api/v1/telegram/broadcast-best` — Run scan and broadcast high-conviction IPOs.
* `POST /api/v1/telegram/digest` — Dispatch Top Picks morning summary digest.
* `POST /api/v1/telegram/webhook/setup` — Register server URL with Telegram Webhook API.
* `POST /api/v1/telegram/webhook` — Process incoming Telegram interactive chat commands (`/start`, `/shares`, etc.).

---

## Quickstart & Installation

### Option A: Docker Compose (Recommended for Production)

Run the full stack (FastAPI app, PostgreSQL 16 database, Caddy reverse proxy with automatic SSL) with a single command:

```bash
# 1. Clone repository
git clone https://github.com/Chinmay468/IPO_PULSE.git
cd IPO_PULSE

# 2. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 3. Launch stack
docker compose up -d --build
```

Access the services:
* **Web Application**: `https://your-domain` (or `http://localhost:8000`)
* **Interactive API Docs**: `http://localhost:8000/docs`
* **PostgreSQL Database**: `localhost:5432` (`db: ipo_db`)

Container management:
```bash
docker compose ps               # Check container status
docker compose logs -f app      # Inspect live logs
docker compose down             # Gracefully stop containers
```

---

### Option B: Local Development Setup

#### 1. Prerequisites
* Python 3.12+
* PostgreSQL 16 (or SQLite for lightweight local testing)

#### 2. Virtual Environment Setup
```bash
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

#### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Environment Configuration
Create a `.env` file based on `.env.example`:
```bash
cp .env.example .env
```

Key variables:
```env
DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/ipo_db"
# Or SQLite:
# DATABASE_URL="sqlite+aiosqlite:///./ipo.db"

ADMIN_USERNAME="admin"
ADMIN_PASSWORD_HASH="<sha256-hash-of-your-password>"
JWT_SECRET_KEY="<your-secure-random-secret>"

# AI Copilot Keys
PRIMARY_LLM_PROVIDER="gemini"
GEMINI_API_KEY="<your-gemini-key>"
GROQ_API_KEY="<your-groq-key>"

# Telegram Bot (Optional)
TELEGRAM_BOT_TOKEN="<token>"
TELEGRAM_CHAT_ID="<chat-id>"
```

Generate password hash:
```bash
python -c "import hashlib; print(hashlib.sha256('your_password'.encode()).hexdigest())"
```

#### 5. Database Migrations
Apply database schema migrations via Alembic:
```bash
alembic upgrade head
```

#### 6. Run the Application
Start the Uvicorn development server:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Testing & Quality Assurance

The codebase includes an extensive suite of **193 automated tests** covering all layers of the application.

```bash
# Run complete test suite
pytest -v

# Run tests with output capture disabled
pytest -s

# Run specific domain test modules
pytest tests/test_scoring.py           # Scoring formulas & weight rules
pytest tests/test_upcoming_discovery.py# Chittorgarh discovery scraper
pytest tests/test_mutual_funds.py      # CAS parsing & Newton-Raphson XIRR
pytest tests/test_technical_analysis.py# Wilder's RSI, EMA, ATR stops
pytest tests/test_portfolio_advisor.py # AI Copilot & multi-key fallback
pytest tests/test_telegram.py          # Telegram webhooks & sanitization
```

---

## Database Migrations

Database schema changes are versioned using **Alembic**.

```bash
# Check current migration status
alembic current

# Apply all pending migrations
alembic upgrade head

# Roll back by one migration
alembic downgrade -1

# Generate a new autogenerated revision
alembic revision --autogenerate -m "describe_schema_change"
```

### Migration History:
* `001_initial_ipo_schema.py` — Base IPO, Subscription, GMP, and Score tables.
* `002_add_ipo_financial_metrics.py` — Balance sheet, P/E, RoNW, and issue size metrics.
* `003_add_suggestion_log.py` — Swing trading suggestions and setup logs.
* `004_add_prediction_tables.py` — Machine learning listing price prediction models.
* `005_add_portfolio_snapshots.py` — Historical net worth and performance snapshots.
* `006_add_mutual_funds_module.py` — Mutual fund schemes, folios, CAS transactions, and NAV history.
* `007_add_technical_diagnoses_table.py` — Technical indicator logs and audit records.
* `008_add_listing_price_to_ipos.py` — Listing day open price and percentage gain tracking.
* `009_add_chittorgarh_scraper_tables.py` — DRHP and detailed issue document metadata.
* `010_add_seed_and_dates_tba_flags.py` — Seed data isolation (`is_seed`) and TBA date handling.

---

## Security & Best Practices

* **Zero Hardcoded Secrets**: Secrets and API keys are strictly configured via environment variables and validated through Pydantic Settings.
* **Log Sanitization**: The logging system automatically scrubs sensitive tokens, Telegram URLs, and API keys before writing to logs.
* **Rate Limiting**: Critical endpoints (Auth login, Link Intime proxy, AI Copilot) are rate-limited via `slowapi` to protect against brute-force attacks and abuse.
* **Single-User Admin JWT**: Protected routes require a valid JWT token issued with SHA-256 password authentication.
* **Safe Scraper Policies**: Respects target server `robots.txt`, implements polite request jitter (2–3s), and avoids crawling discussion forums or login-gated URLs.

---

## License

This project is licensed under the [MIT License](LICENSE).
