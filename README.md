# Async Document Processing Service

An async document processing agent that accepts documents (PDFs, text) via REST API, queues them, and analyzes them using Gemini LLM. Built for the Robotic Imaging AI Agent Engineer assessment.

## Architecture

```
Client ──> FastAPI (API Server, port 8000)
               │
               ├── SQLite DB (jobs + audit_trail tables)
               │        ▲
               │        │ poll for pending jobs
               │        │
               └── Worker Process (background)
                        │
                        └── Gemini API (LLM analysis)
```

**Job State Machine:**
```
PENDING ──> FETCHING ──> PROCESSING ──> VALIDATING ──> COMPLETED
   │            │             │              │
   └────────────┴─────────────┴──────────────┴──────> FAILED
```

Every state transition is recorded in the `audit_trail` table.

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.12 | Async-native, strong typing, rich LLM ecosystem |
| API | FastAPI | Native async, auto OpenAPI docs, Pydantic validation |
| Database | SQLite (aiosqlite) | Zero-config, good enough for single-node, portable |
| LLM | Gemini 2.5 Flash | Free tier available, native PDF upload via File API |
| Logging | structlog | Structured JSON logs with correlation IDs |

## Quick Start

### Prerequisites
- Python 3.10+
- A Gemini API key (get one free at https://aistudio.google.com/apikey)

### 1. Clone and install

```bash
git clone <repo-url>
cd AsyncDocumentProcessingService
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your Gemini API key:
```
GEMINI_API_KEY=your-actual-gemini-key
```

All configuration is via environment variables (no hardcoded secrets):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/docprocessor.db` | SQLAlchemy DB URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis URL (unused in current polling worker) |
| `GEMINI_API_KEY` | `""` | Gemini API key. If empty/placeholder, runs in mock mode |
| `LOG_LEVEL` | `info` | Log level |
| `TOKEN_BUDGET_DEFAULT` | `4096` | Default max tokens per job |
| `MAX_DOCUMENT_SIZE_MB` | `10` | Max document download size |
| `WORKER_CONCURRENCY` | `5` | Worker concurrency (reserved for future use) |
| `MIN_CONFIDENCE_THRESHOLD` | `0.5` | Minimum confidence to accept LLM output |

### 3. Create the data directory

```bash
mkdir -p data
```

The SQLite database file is created automatically at `data/docprocessor.db` on first startup.

### 4. Start the API server

```bash
python run.py
```

The API server starts at `http://localhost:8000`. On startup it:
- Initializes structured JSON logging
- Creates all database tables (jobs, audit_trail) via SQLAlchemy `create_all`
- Registers all route handlers

### 5. Start the worker (separate terminal)

```bash
source venv/bin/activate
python -m src.worker.main
```

The worker process:
- Creates DB tables if they don't exist
- Recovers any stale jobs (stuck in non-terminal states for >5 min) back to `pending`
- Polls the DB every 2 seconds for pending jobs
- Processes each job through the state machine: fetch doc -> call LLM -> validate -> complete

## Database

### Tables

**jobs** - Main job table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (string) | Primary key |
| `idempotency_key` | VARCHAR(64) | SHA-256 hash of `(document_url, analysis_type)`. Unique. |
| `document_url` | TEXT | URL of the document to process |
| `analysis_type` | VARCHAR(20) | `summary`, `extraction`, or `classification` |
| `status` | VARCHAR(20) | Current state: `pending`, `fetching`, `processing`, `validating`, `completed`, `failed` |
| `result` | JSON | Analysis output (null until completed) |
| `error` | JSON | Error details `{type, detail}` (null unless failed) |
| `token_usage` | JSON | `{input_tokens, output_tokens, total_tokens}` |
| `token_budget` | INTEGER | Max tokens allowed for this job |
| `metadata` | JSON | Extensible metadata field |
| `created_at` | DATETIME | Job creation timestamp (UTC) |
| `updated_at` | DATETIME | Last update timestamp (UTC) |
| `completed_at` | DATETIME | Completion/failure timestamp (UTC) |

**audit_trail** - Every state transition is logged

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `job_id` | UUID (FK) | References `jobs.id` |
| `from_state` | VARCHAR(20) | Previous status (null for job creation) |
| `to_state` | VARCHAR(20) | New status |
| `reason` | TEXT | Human-readable reason for the transition |
| `timestamp` | DATETIME | When the transition happened (UTC) |

### Inspecting the database

```bash
sqlite3 data/docprocessor.db

-- List all jobs
SELECT id, status, analysis_type, created_at FROM jobs;

-- View audit trail for a job
SELECT from_state, to_state, reason, timestamp FROM audit_trail WHERE job_id = '<job-id>' ORDER BY timestamp;

-- Check token spend
SELECT id, json_extract(token_usage, '$.total_tokens') as tokens FROM jobs WHERE token_usage IS NOT NULL;
```

## API Endpoints

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

### POST /jobs
Submit a document for analysis. Returns immediately with a job ID (async processing).

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "document_url": "https://arxiv.org/pdf/1706.03762",
    "analysis_type": "summary"
  }'
```

**Response (202 Accepted):**
```json
{
  "id": "a1b2c3d4-...",
  "status": "pending",
  "message": "Job accepted"
}
```

**Idempotency:** Submitting the same `(document_url, analysis_type)` pair returns the existing job instead of creating a duplicate.

**Analysis types:** `summary`, `extraction`, `classification`

### GET /jobs/:id
Check status and retrieve results.

```bash
curl http://localhost:8000/jobs/a1b2c3d4-...
```

### GET /jobs
List jobs with optional filters.

```bash
# All jobs
curl http://localhost:8000/jobs

# Filter by status
curl "http://localhost:8000/jobs?status=completed"

# Filter by type + pagination
curl "http://localhost:8000/jobs?analysis_type=summary&limit=10&offset=0"

# Filter by date range
curl "http://localhost:8000/jobs?created_after=2025-01-01T00:00:00&created_before=2025-12-31T23:59:59"
```

### GET /healthz
Liveness check. Actually verifies the DB connection (runs `SELECT 1`).

```bash
curl http://localhost:8000/healthz
```

**Response:**
```json
{
  "status": "healthy",
  "checks": { "db": "ok" }
}
```

Returns `200` with `"healthy"` only if the DB is reachable. Otherwise returns `"degraded"` with error details.

### GET /metrics
Operational metrics queried from the database.

```bash
curl http://localhost:8000/metrics
```

**Response:**
```json
{
  "total_jobs": 42,
  "jobs_by_status": { "completed": 35, "failed": 3, "pending": 4 },
  "error_rate": 0.0714,
  "avg_latency_seconds": 12.5,
  "total_token_spend": 84000
}
```

## Mock Mode

If `GEMINI_API_KEY` is empty or set to a placeholder (`your-gemini-key-here`, `mock-key`), the agent runs in **mock mode** — it returns hardcoded results without calling the Gemini API. This is useful for testing the full pipeline without spending API credits.

## Worker Crash Recovery

If the worker crashes mid-job, the job stays in a non-terminal state (`fetching`, `processing`, `validating`). On the next worker startup, `recover_stale_jobs()` finds any jobs stuck for >5 minutes and resets them to `pending` so they get re-processed. This ensures no job is lost.

## PENDING

1. How to handle high worker traffic -> add async concurrency between claim and process
2. Add active worker count tracking and use it for load balancing
