# Automated Stock Market Data Pipeline

An automated ETL pipeline for A-share (China stock market) daily market data: it extracts daily quotes from public data sources, cleans and models them in layers, runs data quality tests, and loads the result into a PostgreSQL data warehouse. It runs on a daily schedule and is idempotent (re-running does not duplicate data).

**Tech stack:** Python (extraction) · PostgreSQL (warehouse) · dbt (transformation & testing) · cron (scheduling)

**Repository:** https://github.com/liuluwell/stock_data_analysis

---

## Architecture

```
Public data sources via akshare (Tencent primary, EastMoney fallback, auto-failover)
        │  Python extraction (multi-source adapters + idempotent upsert)
        ▼
raw layer  ── raw_stock_daily        raw data, no business transformation (ELT principle)
        │  dbt (source → staging)
        ▼
staging layer ── stg_stock_daily     cleaned & field-standardized (view)
        │  dbt (ref dependency → marts)
        ▼
marts layer ── mart_stock_daily_summary   analytical summary with derived metrics (materialized table)
        │
        ▼
Data quality tests (dbt test: not_null / combination uniqueness / accepted_values)
```

The layering maps to the classic data-warehouse ODS → DWD → DWS model, implemented with dbt's source / staging / marts pattern.

---

## Project Structure

```
stock_data_analysis/
├── config.py                       # stock pool, extraction parameters
├── fetch_stock.py                  # main extraction script (multi-source, idempotent load)
├── requirements.txt                # Python dependencies
├── .env                            # DB connection (not committed, see .env.example)
├── .env.example                    # environment variable template
├── sql/
│   ├── 1.raw_stock_daily.sql       # DDL for the raw market-data table
│   └── 2.raw_stock_basic_info.sql  # DDL for basic-info table (reserved for future use, not yet enabled)
└── stock_dbt/                      # dbt project
    ├── dbt_project.yml
    ├── packages.yml                # depends on dbt_utils
    └── models/
        ├── staging/
        │   ├── sources.yml         # raw-layer source declaration + tests
        │   ├── stg_stock_daily.sql
        │   └── stg_stock_daily.yml # staging-layer tests
        └── marts/
            └── mart_stock_daily_summary.sql
```

---

## Requirements

- Python 3.11+
- PostgreSQL 15+
- Deployment environment: Linux (currently deployed on Debian 12, single 1GB-RAM host)

---

## Setup & Run

### 1. Create database and tables

```sql
CREATE DATABASE stock_data;
```

Connect to `stock_data`, then run `sql/1.raw_stock_daily.sql` to create the raw table.

### 2. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure the database connection

Copy `.env.example` to `.env` and fill in the actual connection details (secrets like the password are never hard-coded or committed):

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stock_data
DB_USER=postgres
DB_PASSWORD=your_password
```

### 4. Run manually

```bash
# Extract: fetch market data for the stock pool into the raw layer
python fetch_stock.py

# Transform + test: build staging / marts and run data quality tests
cd stock_dbt && dbt run && dbt test
```

The current stock pool (`config.py`): `000001` (Ping An Bank), `600519` (Kweichow Moutai), `300750` (CATL). Changing the stock pool only requires editing `config.py`; no changes to the main logic are needed.

---

## Data Layers

**raw layer (`raw_stock_daily`)**
Raw market data landed as-is, with no business transformation (ELT principle). Includes open/close/high/low, volume, amount, daily change, amplitude, turnover rate, plus `data_source` (which source it came from) and `fetched_at` (fetch time) for traceability.

**staging layer (`stg_stock_daily`, view)**
Cleaning and standardization: rename fields to English, normalize types, apply basic quality filters (`close > 0`, `open > 0`, `high >= low`). Still at detail grain. Materialized as a view, always reflecting the latest raw data.

**marts layer (`mart_stock_daily_summary`, materialized table)**
Adds analysis-oriented derived metrics on top of the detail data:
- `price_direction`: up / down / flat
- `avg_price`: daily average price (amount / shares traded)

Dependencies are declared via `ref('stg_stock_daily')`, so dbt orchestrates execution order automatically. Materialized as a table for faster queries.

---

## Data Quality Tests

dbt tests turn data quality into an automated, verifiable safeguard, covering three types:

| Test type | Coverage | Purpose |
|---|---|---|
| `not_null` | symbol, trade_date, close_price | key fields are not null |
| combination uniqueness | symbol + trade_date | verifies no duplicate data (a data-level proof of idempotency) |
| `accepted_values` | price_direction ∈ {up, down, flat} | business-rule constraint |

Run with `dbt test`; all currently pass.

---

## Idempotency

The pipeline is designed so that **re-running does not create duplicate data** — a core requirement for long-running scheduled jobs.

**Implementation:** the raw table has a `UNIQUE(symbol, trade_date)` constraint, and inserts use
`INSERT ... ON CONFLICT (symbol, trade_date) DO UPDATE` — existing records are updated rather than duplicated.

**Verification:** run `fetch_stock.py` twice in a row and compare the results —
- row count and primary-key ids are unchanged (no new duplicate rows)
- business data is identical
- only `fetched_at` timestamps update (proving the script actually re-ran, but data was not duplicated)

The combination-uniqueness dbt test passing further proves, at the data level, that there are no duplicates.

---

## Scheduling

Currently scheduled with **cron** (runs extraction and transformation automatically after each trading day's close):

```cron
0  19 * * 1-5  cd /root/stock_data_analysis && /root/stock_data_analysis/venv/bin/python fetch_stock.py >> /root/stock_data_analysis/logs/cron.log 2>&1
30 19 * * 1-5  cd /root/stock_data_analysis/stock_dbt && /root/stock_data_analysis/venv/bin/dbt run >> /root/stock_data_analysis/logs/dbt.log 2>&1
```

> **A note on the scheduling choice**
> Production data platforms typically use dedicated orchestrators such as Airflow / DolphinScheduler / XXL-JOB / Azkaban, which provide task dependency orchestration, retries, alerting, visualization, and centralized management — none of which cron offers.
> This project currently runs on a single 1GB-RAM host, which is not enough to run those orchestrators (their resource footprint is significant), so cron is used as a lightweight substitute that satisfies the basic "run on a schedule" need.
> **A production deployment should migrate to Airflow or XXL-JOB.**

---

## Known Limitations

**1. Data source reliability**
akshare relies on public web interfaces, which are subject to anti-scraping measures, rate limiting, and occasional dropped connections. This project mitigates that with multi-source auto-failover (Tencent primary, EastMoney fallback) and request rate limiting, but **free data sources are not suitable for serious quantitative research**. A long-term solution should evaluate paid data sources (e.g. Tushare Pro, Tonghuashun iFinD).

**2. Volume unit inconsistency (affects avg_price)**
Testing revealed that the Tencent data source returns inconsistent `volume` units across **different stocks** (some in shares, some in lots), causing an approximately 100x deviation in `mart_stock_daily_summary.avg_price` for some stocks.
- **Identified**; this is not a code bug but a data-source data-quality issue.
- **Planned fix:** in the marts layer, infer the correct unit using the business invariant that "the average price must fall between the day's low and high," rather than hard-coding a fixed conversion factor. The raw layer keeps the original value and the transformation logic lives in the dbt layer, consistent with the ELT layering principle.

---

## Roadmap

- Fix the volume-unit issue affecting avg_price (approach above)
- Add a market-daily-overview marts table (aggregated by trade date: advancers count, average change, total turnover)
- Introduce a basic-info table (sector/industry) for sector-level wide tables and summaries
- dbt multi-environment management (dev/prod targets in profiles.yml)
- Upgrade to a reliable paid data source
- Replace cron with a production-grade orchestrator (Airflow / XXL-JOB)