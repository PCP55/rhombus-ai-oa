# Distributed NL-to-Regex Data Processing Platform

A web app that lets users upload a CSV/Excel file, describe a text pattern in
plain English (e.g. *"find email addresses"*), and replace every match at
scale. The natural-language description is turned into a regex by an LLM,
and the actual find-and-replace runs as a distributed PySpark job on a
Celery worker — so the web server stays responsive even on multi-million-row
files.

**Current status:** End-to-end pipeline is working on a DigitalOcean Droplet
(bare IP, no TLS yet). Two-step upload → column dropdown → async processing
with live progress is implemented. Large-file testing is in progress
(~1.2 GB CSV). Demo video still to be recorded.

## Demo Video

*Recording in progress — will be embedded here.* The video will walk through
uploading a file, submitting a natural-language rule, watching the job
progress live, and viewing the paginated processed output.

## Contents

- [Architecture](#architecture)
- [API endpoints](#api-endpoints)
- [Repository layout](#repository-layout)
- [Setup & run (Docker Compose)](#setup--run-docker-compose)
- [Using the app](#using-the-app)
- [Asynchronous processing: Celery + Redis](#asynchronous-processing-celery--redis)
- [Distributed processing: PySpark](#distributed-processing-pyspark)
- [LLM integration & regex safety](#llm-integration--regex-safety)
- [Large-file / scale testing](#large-file--scale-testing)
- [Deployment notes](#deployment-notes)
- [Trade-offs & known limitations](#trade-offs--known-limitations)

## Architecture

```
                    ┌─────────────┐
   Browser  ─────▶  │  Next.js    │  (frontend/, port 3000)
   Basic Auth        │  frontend   │  upload progress via XHR
                    └──────┬──────┘
                           │ fetch() / XHR + X-Access-Key
                           ▼
                    ┌─────────────┐          ┌───────────────┐
                    │   Django    │  ───────▶│     Redis     │
                    │  web (API)  │  cache/  │ broker (db 0) │
                    │ port 8000   │  broker  │ cache  (db 1) │
                    └──────┬──────┘          └───────┬───────┘
                           │ enqueue                  │
                           │ ProcessingJob row        │ pick up task
                           ▼                          ▼
                    ┌─────────────┐          ┌───────────────┐
                    │   SQLite    │◀────────▶│ Celery worker │
                    │ (job state) │  update  │ (tasks.py)    │
                    └─────────────┘  status/ └───────┬───────┘
                                      progress        │ submit job
                                                       ▼
                                             ┌───────────────────┐
                                             │  Spark master +   │
                                             │  Spark worker      │
                                             │ (services/spark.py)│
                                             └───────────────────┘
```

### Request flow (two-step upload)

Large files are only transferred once. The UI splits the work into two API
calls so column discovery doesn't require a second upload:

```
1. POST /api/upload/     → store file, read header row, return column names
                           (ProcessingJob status: DRAFT)
2. POST /api/submit/     → attach column + NL prompt + replacement, queue Celery
                           (status: DRAFT → QUEUED → RUNNING → SUCCESS/FAILED)
3. GET  /api/status/     → poll every 2s for progress + result
4. GET  /api/results/    → paginated processed rows (once SUCCESS)
```

### Why this stack

- **Django** owns the API, the `ProcessingJob` model (status/progress
  persistence), and URL routing. It is intentionally thin — it creates job
  rows and hands off to Celery; it never runs Spark or LLM calls inline.
  The one synchronous file touch is reading a single header line for the
  column dropdown (`services/read_columns.py`).
- **Celery + Redis** decouple the request/response cycle from the actual
  work. `submit_job()` returns a `job_id` in milliseconds; all parsing,
  LLM calls, and Spark orchestration happen later in a worker process.
  Redis plays two independent roles — message broker/result backend for
  Celery (db 0), and a cache for LLM-generated regex patterns (db 1) — on
  the same Redis container with separate logical databases.
- **PySpark** is the transformation engine. `regexp_replace` runs as a column
  expression across partitions, not a Python loop over rows, so the same code
  path that works for a 100-row CSV also works for a 10-million-row one.
- **Next.js** shows upload progress (XHR), polls job status every 2s, renders
  a progress bar driven by `job.progress`, and swaps to a paginated results
  table once the job succeeds.

### Middleware & security layers (Django)

Middleware order matters — `CorsMiddleware` is listed first so every
response (including short-circuited 401/413 errors) gets CORS headers:

| Middleware | Role |
|------------|------|
| `CorsMiddleware` | CORS headers on all responses (must be outermost) |
| `MaxUploadSizeMiddleware` | Rejects oversized `Content-Length` with 413 |
| `RequireAccessKeyMiddleware` | `X-Access-Key` gate via `hmac.compare_digest` |

The frontend adds a second gate: HTTP Basic Auth on the Next.js site itself
(`frontend/middleware.ts`). See [Deployment notes](#deployment-notes).

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/upload/` | Stage file, return `job_id` + `columns` (DRAFT) |
| `POST` | `/api/submit/<job_id>/` | Attach inputs, queue Celery (→ QUEUED) |
| `GET` | `/api/status/<job_id>/` | Poll status, progress, result/error |
| `POST` | `/api/cancel/<job_id>/` | Cancel running job or discard DRAFT |
| `GET` | `/api/results/<job_id>/` | Paginated processed rows (`?page=&limit=`) |

All `POST` endpoints are `@csrf_exempt` because the API is stateless (no
session cookie) and authorized via `X-Access-Key` + CORS instead.

## Repository layout

```
rhombus-ai-oa/
├── backend/                      # Django project
│   ├── api/
│   │   ├── models.py             # ProcessingJob (DRAFT/QUEUED/RUNNING/…)
│   │   ├── views.py              # upload / submit / status / cancel / results
│   │   ├── tasks.py              # Celery task: LLM → Spark → save result
│   │   ├── middleware.py         # access-key gate + upload size cap
│   │   └── services/
│   │       ├── read_columns.py   # read header row only (CSV/Excel)
│   │       ├── llm.py            # NL → regex via Gemini + ReDoS guard
│   │       └── spark.py          # Spark transformation + chunked write
│   ├── core/                     # settings.py, urls.py, celery.py
│   └── Dockerfile
├── frontend/                      # Next.js app
│   ├── app/page.tsx               # upload + form + polling state machine
│   ├── components/                # FileDropzone, ExtractionForm, ResultsTable
│   ├── lib/api.ts                 # apiFetch + apiUploadWithProgress (XHR)
│   ├── middleware.ts              # HTTP Basic Auth gate
│   └── Dockerfile
├── docker-compose.yaml            # redis, web, worker, spark, spark-worker, frontend
├── .env.example                   # root config (Django, access gate, frontend)
└── backend/.env.example           # backend-only (GOOGLE_API_KEY, local dev)
```

## Setup & run (Docker Compose)

**Prerequisites:** Docker + Docker Compose, and a Google Gemini API key
(the LLM step uses `langchain-google-genai`).

### 1. Configure environment variables

There are two separate `.env` files because of how they're consumed:

| File | Used by | Purpose |
|------|---------|---------|
| `.env` (repo root) | `docker-compose.yaml` | Django security, access gate, frontend build args, `MAX_UPLOAD_SIZE_MB` |
| `backend/.env` | `load_dotenv()` in `settings.py` | `GOOGLE_API_KEY` for local/non-Compose runs |

```bash
cp .env.example .env
cp backend/.env.example backend/.env
# edit backend/.env and set GOOGLE_API_KEY=<your Gemini key>
```

For local dev, the defaults (`DJANGO_DEBUG=True`, no access key) are enough.
For deployment, see [Deployment notes](#deployment-notes).

**Large files:** bump `MAX_UPLOAD_SIZE_MB` in the root `.env` (default 200).
A 1.2 GB file needs at least `MAX_UPLOAD_SIZE_MB=2048`, and the droplet needs
~3 GB free disk (Django spools to temp, then copies to `media/`).

### 2. Start the stack

```bash
docker compose up --build
```

This starts: `redis`, `web` (Django `:8000`), `worker` (Celery),
`spark` + `spark-worker`, and `frontend` (Next.js `:3000`).

The `web` service runs `python manage.py migrate --noinput` on every
startup, so database migrations apply automatically — no manual migrate step
needed after the first `docker compose up`.

### 3. Open the app

**http://localhost:3000**

To run the backend directly on the host instead (faster iteration), see
`backend/Makefile` — you'll need `uv`, local Redis, and Spark, so Docker
Compose is the easier path.

## Using the app

### Job state machine (frontend)

```
"" → INSPECTING → DRAFT → SUBMITTING → QUEUED → RUNNING → SUCCESS/FAILED
```

- **INSPECTING** — file is uploading (XHR progress bar) and/or server is
  reading the header row.
- **DRAFT** — file is on the server, column dropdown is populated; user
  fills in the form.
- **QUEUED / RUNNING** — Celery worker is processing; progress bar polls
  `/api/status/` every 2s.
- **SUCCESS / FAILED** — terminal states; results table or error message.

### Steps

1. Drop a `.csv`, `.xls`, or `.xlsx` file. Upload progress is shown in real
   time (percent + bar). Column names come back for a **dropdown**.
2. Pick the target column, describe the pattern in plain English, and enter
   the replacement value.
3. Submit — the file was already uploaded in step 1, so this is instant.
   A live progress bar tracks Celery/Spark processing.
4. Once the job succeeds, a paginated table of processed data appears.
   Cancel a running job at any time.

### Validation

- **File extension** — only `.csv`, `.xls`, `.xlsx` accepted (`views.py`).
- **Target column** — server-side allowlist against columns read at upload
  time (`ProcessingJob.columns` JSONField); the dropdown is a UX convenience,
  not the security boundary.
- **Regex** — LLM output is syntax-checked and ReDoS-probed before Spark
  sees it (`services/llm.py`).

## Asynchronous processing: Celery + Redis

**Broker & result backend.** Both use Redis logical database `0`:

```python
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
```

The LLM-regex **cache** uses logical database `1` (`django-redis` in
`CACHES`). Same Redis container, zero extra infrastructure — but a cache
flush can never wipe in-flight Celery task state.

**The one Celery task.** `process_file_task` (`backend/api/tasks.py`) does
everything the web process cannot do inline: resolve the regex (cache-or-LLM),
convert Excel to CSV via Polars if needed, and call `process_data_with_spark`.
Logging uses Python's `logging` module (not `print`) with a `LOGGING` config
in `settings.py` so `INFO`-level messages appear in `docker compose logs`.

**Progress reporting.** The Celery task ID is pinned to the job's UUID
(`apply_async(args=[job.id], task_id=str(job.id))`) so the polling endpoint
can look up live state via `AsyncResult(str(job.id))`:

| Stage | `job.progress` |
|-------|-----------------|
| Job picked up by worker | 10% |
| Regex resolved (cache or LLM) | 30% |
| Spark rows processed | 50% → 95%, scaled to `rows_processed / total_rows` |
| Job complete | 100% |

Row-level progress comes from `services/spark.py`: the DataFrame is
repartitioned into `NUM_PROGRESS_CHUNKS` (10) pieces, each written
separately, and a `progress_callback` fires after every chunk. The Celery
task writes both `job.progress` (DB) and `self.update_state(..., meta={...})`
(Celery), which `check_status()` surfaces as `progress_detail` while
`RUNNING`.

**Failure and cancellation.**
- Failures are recorded on the job row and surfaced via `/api/status/` — the
  task does not auto-retry (avoids re-running Spark on permanent errors like
  bad regex or missing files).
- Cancellation calls `revoke(task_id, terminate=True, signal="SIGKILL")` to
  kill a stuck Spark/JVM process, then marks the job `FAILED`.

## Distributed processing: PySpark

`services/spark.py` reads the CSV with `spark.read.csv(...)`, applies
`regexp_replace` as a column expression via `withColumn`, and writes the
result as Parquet chunks.

**Partitioning choice.** After `df.count()` (needed for progress), the
transformed DataFrame is repartitioned to `NUM_PROGRESS_CHUNKS = 10`
(`min(10, max(1, total_rows))`). Each partition is written separately with
a progress callback. This keeps progress reporting predictable regardless of
file size, at the cost of not auto-tuning partition count to cluster resources.

Reading back for the UI (`get_paginated_results`) uses `polars.scan_parquet(...)`
— a lazy scan — then `.slice(offset, limit).collect()` for only the requested
page. The full result set lives on disk; only ~50 rows at a time hit the browser.

Spark runs as two Compose services (`spark`, `spark-worker`), memory-capped
(512M / 1G) with `spark.cores.max = 1`, so a single job can't starve the rest
of the stack on a small Droplet.

## LLM integration & regex safety

`services/llm.py` uses `langchain-google-genai` (Gemini) with a few-shot
prompt to turn natural language into a regex string. `validate_regex()` runs
two checks before caching or handing to Spark:

1. **Syntax validity** — `re.compile(pattern)`; `re.error` surfaces as the
   job's `error_message`.
2. **ReDoS guard** — adversarial probe strings (120 chars each) run under a
   500ms `SIGALRM` timeout. Patterns that don't resolve in time are rejected.
   **Caveat:** this validates Python's `re` engine; Spark runs on the JVM
   (`java.util.regex`), which can behave differently in edge cases.

Only patterns passing both checks are cached in Redis (`regex_prompt_<prompt>`,
24h TTL).

## Large-file / scale testing

**In progress.** A ~1.2 GB CSV is being tested against the live Droplet
deployment. Key configuration for large uploads:

| Setting | Default | Notes |
|---------|---------|-------|
| `MAX_UPLOAD_SIZE_MB` | 200 | Set to 2048+ for multi-GB files |
| `FILE_UPLOAD_TEMP_DIR` | `media/.upload-tmp` | Spools large uploads to the mounted volume, not container `/tmp` |
| Disk space | — | Need ~3× file size free briefly (temp + final copy) |

Planned methodology once the 1.2 GB run completes:

1. Record total rows, wall-clock time from `QUEUED` → `SUCCESS`, and
   `job.progress` cadence during the run.
2. Confirm paginated results stay fast regardless of total row count.

| Rows | File size | End-to-end time | Notes |
|------|-----------|------------------|-------|
| _TBD_ | ~1.2 GB | _TBD_ | Upload + processing test in progress |

## Deployment notes

Deployed on a bare DigitalOcean Droplet IP (no domain/TLS yet). Three
independent controls gate access:

| Layer | Mechanism | Config |
|-------|-----------|--------|
| Site | HTTP Basic Auth | `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` (runtime) |
| API | `X-Access-Key` header | `APP_ACCESS_KEY` / `NEXT_PUBLIC_APP_ACCESS_KEY` (build-time for frontend) |
| Upload size | `Content-Length` check | `MAX_UPLOAD_SIZE_MB` (runtime) |

See `.env.example` for the full variable list and build-time vs. runtime notes.

### Pre-launch checklist

Before sharing the deployed URL with a grader:

- [ ] `DJANGO_DEBUG=False` with a real `DJANGO_SECRET_KEY`
- [ ] `APP_ACCESS_KEY` and `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` set
- [ ] `MAX_UPLOAD_SIZE_MB` set high enough for your test file
- [ ] `DJANGO_ALLOWED_HOSTS` and `DJANGO_CORS_ALLOWED_ORIGINS` include the Droplet IP
- [ ] `NEXT_PUBLIC_API_BASE_URL` points at the API's public URL (rebuild frontend after changing)
- [ ] Django `/admin/` has no superuser, or a strong password if one exists
- [ ] Enough disk space on the Droplet for the largest test file (~3× file size)
- [ ] Understand that without TLS, credentials and file contents travel in cleartext

### Redeploying after code changes

```bash
git pull
docker compose up --build -d
# migrations run automatically on web startup
# if frontend env vars changed, rebuild frontend:
docker compose up --build -d frontend
```

## Trade-offs & known limitations

- **Single target column.** Model, API, and UI take one column name. Extending
  to multi-column would mean looping `withColumn` in `services/spark.py`.
- **No Celery auto-retry.** Failed jobs are marked `FAILED` once rather than
  retried — simpler for a demo deployment; production would retry only
  transient errors (Redis blips, Spark timeouts).
- **SQLite for job state.** Fine for a single-Droplet demo; production would
  use Postgres to avoid single-writer lock under concurrent updates.
- **Django dev server.** `runserver` handles uploads synchronously and is not
  production-grade. Adequate for this assessment; a real deployment would use
  Gunicorn/Uvicorn behind a reverse proxy with proper upload timeouts.
- **No automated tests yet** for the Celery task or Spark service layer
  (`backend/api/tests.py` covers regex validation and column reading) —
  verified manually end-to-end.
- **Orphaned DRAFT jobs.** Abandoned uploads (user leaves after step 1) are
  never cleaned up. A periodic cleanup task and per-IP rate limit would be
  needed for a long-lived deployment.
- **ReDoS guard is Python-only.** JVM regex behavior in Spark is not probed;
  see [LLM integration](#llm-integration--regex-safety).
- **Excel column read loads full file.** `pl.read_excel()` in `read_columns.py` is
  synchronous on the web tier. Acceptable because Excel files are not the
  multi-GB case PySpark is responsible for.
