# Distributed NL-to-Regex Data Processing Platform

A web app that lets users upload a CSV/Excel file, describe a text pattern in plain English (e.g. _"find email addresses"_), and replace every match at scale. The natural-language description is turned into a regex by an LLM,
and the actual find-and-replace runs as a distributed PySpark job on a Celery worker — so the web server stays responsive even on multi-million-row files.

## Demo Video

[Youtube](https://youtu.be/eRQj0PhXE7c)

The video walks through uploading a file, submitting a natural-language rule, watching the job progress live, and viewing the paginated processed output.

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

Large files are only transferred once. The UI splits the work into two API calls so column discovery doesn't require a second upload:

```
1. POST /api/upload/     → store file, queue column discovery (DRAFT)
                           poll GET /api/status/ until columns appear
2. POST /api/submit/     → attach inputs, queue Celery (→ QUEUED → RUNNING → SUCCESS/FAILED)
3. GET  /api/status/     → poll every 2s for progress + result
4. GET  /api/results/    → paginated processed rows (once SUCCESS)
```

### Why this stack

- **Django** owns the API, the `ProcessingJob` model (status/progress persistence), and URL routing. It is intentionally thin — it stores uploads, enqueues Celery tasks, and serves status/results. It never runs Spark, LLM calls, or file parsing inline (column discovery runs in `read_columns_task`).
- **Celery + Redis** decouple the request/response cycle from the actual work. `submit_job()` returns a `job_id` in milliseconds; all parsing, LLM calls, and Spark orchestration happen later in a worker process. Redis plays two independent roles — message broker/result backend for Celery (db 0), and a cache for LLM-generated regex patterns (db 1) — on the same Redis container with separate logical databases.
- **PySpark** is the transformation engine. `regexp_replace` runs as a column expression across partitions, not a Python loop over rows.
- **Next.js** shows upload progress (XHR), polls job status every 2s, renders a progress bar driven by `job.progress`, and swaps to a paginated results table once the job succeeds.

## API endpoints

| Method | Path                     | Purpose                                    |
| ------ | ------------------------ | ------------------------------------------ |
| `POST` | `/api/upload/`           | Stage file, queue column discovery (DRAFT) |
| `POST` | `/api/submit/<job_id>/`  | Attach inputs, queue Celery (→ QUEUED)     |
| `GET`  | `/api/status/<job_id>/`  | Poll status, progress, result/error        |
| `POST` | `/api/cancel/<job_id>/`  | Cancel running job or discard DRAFT        |
| `GET`  | `/api/results/<job_id>/` | Paginated processed rows (`?page=&limit=`) |

## Repository layout

```
rhombus-ai-oa/
├── backend/                      # Django project
│   ├── api/
│   │   ├── models.py             # ProcessingJob (DRAFT/QUEUED/RUNNING/…)
│   │   ├── views.py              # upload / submit / status / cancel / results
│   │   ├── tasks.py              # Celery: column read, LLM → Spark pipeline
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

### 1. Configure environment variables

There are two separate `.env` files because of how they're consumed:

| File               | Used by                          | Purpose                                                                 |
| ------------------ | -------------------------------- | ----------------------------------------------------------------------- |
| `.env` (repo root) | `docker-compose.yaml`            | Django security, access gate, frontend build args, `MAX_UPLOAD_SIZE_MB` |
| `backend/.env`     | `load_dotenv()` in `settings.py` | `GOOGLE_API_KEY` for local/non-Compose runs                             |

**Large files:** bump `MAX_UPLOAD_SIZE_MB` in the root `.env`.

### 2. Start the stack

```bash
docker compose up --build -d
```

This starts: `redis`, `web` (Django `:8000`), `worker` (Celery),
`spark` + `spark-worker`, and `frontend` (Next.js `:3000`).

The `web` service runs `python manage.py migrate --noinput` on every
startup, so database migrations apply automatically — no manual migrate step
needed after the first `docker compose up`.

### 3. Open the app

## Using the app

### Job state machine (frontend)

```
"" → INSPECTING → DRAFT → SUBMITTING → QUEUED → RUNNING → SUCCESS/FAILED
```

- **INSPECTING** — file is uploading (XHR progress bar) and/or a Celery worker is reading column names in the background.
- **DRAFT** — file is on the server, column dropdown is populated; user fills in the form.
- **QUEUED / RUNNING** — Celery worker is processing; progress bar polls `/api/status/` every 2s.
- **SUCCESS / FAILED** — terminal states; results table or error message.

### Steps

1. Drop a `.csv`, `.xls`, or `.xlsx` file. Upload progress is shown in real time (percent + bar). Column names come back for a **dropdown**.
2. Pick the target column, describe the pattern in plain English, and enter the replacement value.
3. Submit — the file was already uploaded in step 1, so this is instant. A live progress bar tracks Celery/Spark processing.
4. Once the job succeeds, a paginated table of processed data appears. Cancel a running job at any time.

### Validation

- **File extension** — only `.csv`, `.xls`, `.xlsx` accepted (`views.py`).
- **Target column** — server-side allowlist against columns read at upload time (`ProcessingJob.columns` JSONField); the dropdown is a UX convenience.
- **Regex** — LLM output is syntax-checked and ReDoS-probed before Spark sees it (`services/llm.py`).

## Asynchronous processing: Celery + Redis

**Broker & result backend.** Both use Redis logical database `0`:

The LLM-regex **cache** uses logical database `1` (`django-redis` in `CACHES`). Same Redis container, zero extra infrastructure — but a cache flush can never wipe in-flight Celery task state.

**The Celery tasks.** Two background tasks in `backend/api/tasks.py`:

- `read_columns_task` — parses the uploaded file header (CSV or Excel) so the web process never does file parsing inline.
- `process_file_task` — resolves the regex (cache-or-LLM), converts Excel to CSV if needed, and runs Spark.

Logging uses Python's `logging` module with a `LOGGING` config in `settings.py` so `INFO`-level messages appear in `docker compose logs`.

**Progress reporting.** The Celery task ID is pinned to the job's UUID (`apply_async(args=[job.id], task_id=str(job.id))`) so the polling endpoint can look up live state via `AsyncResult(str(job.id))`:

| Stage                         | `job.progress`                                     |
| ----------------------------- | -------------------------------------------------- |
| Job picked up by worker       | 10%                                                |
| Regex resolved (cache or LLM) | 30%                                                |
| Spark rows processed          | 50% → 95%, scaled to `rows_processed / total_rows` |
| Job complete                  | 100%                                               |

Row-level progress comes from `services/spark.py`: the DataFrame is repartitioned into `NUM_PROGRESS_CHUNKS` (10) pieces, each written separately, and a `progress_callback` fires after every chunk. The Celery task writes both `job.progress` (DB) and `self.update_state(..., meta={...})` (Celery), which `check_status()` surfaces as `progress_detail` while `RUNNING`.

**Failure, retries, and cancellation.**

- Transient failures (Redis blips, Spark timeouts) retry up to 3 times with
  exponential backoff (30s → 60s → 120s). Permanent errors (bad regex, missing
  file, empty columns) fail immediately without retry.
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
page. The full result set lives on disk; only ~25 rows at a time hit the browser.

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

## Trade-offs & known limitations

- **Excel is not a native Spark input.** PySpark reads CSV directly; .xls/.xlsx files are converted to CSV in the Celery worker via Polars before Spark runs. That adds an extra step and means Excel is loaded into memory twice (once for column discovery, once for conversion).
- **Column validation reads the file early.** To populate the target-column dropdown and reject invalid names server-side, the uploaded file is parsed in a background Celery task (read_columns_task) before processing starts. CSV files only need the header row; Excel files are fully loaded via Polars to extract column names.
- **Orphaned DRAFT jobs.** Abandoned uploads (user leaves after step 1) are
  never cleaned up. A periodic cleanup task and per-IP rate limit would be
  needed for a long-lived deployment.
- **ReDoS guard is Python-only.** JVM regex behavior in Spark is not probed.
