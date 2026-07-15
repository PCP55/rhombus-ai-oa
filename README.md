# Distributed NL-to-Regex Data Processing Platform

A web app that lets users upload a CSV/Excel file, describe a text pattern in
plain English (e.g. *"find email addresses"*), and replace every match at
scale. The natural-language description is turned into a regex by an LLM,
and the actual find-and-replace runs as a distributed PySpark job on a
Celery worker — so the web server stays responsive even on multi-million-row
files.

## Demo Video

*Recording in progress — will be embedded here.* The video will walk through
uploading a file, submitting a natural-language rule, watching the job
progress live, and viewing the paginated processed output.

## Contents

- [Architecture](#architecture)
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
                    │  frontend   │
                    └──────┬──────┘
                           │ fetch() + X-Access-Key
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

**Why this stack:**

- **Django** owns the API, the `ProcessingJob` model (status/progress
  persistence), and URL routing. It is intentionally thin — it only ever
  creates a job row and hands off to Celery; it never touches the uploaded
  file's contents itself.
- **Celery + Redis** decouple the request/response cycle from the actual
  work. `upload_file()` returns a `job_id` in milliseconds; all parsing,
  LLM calls, and Spark orchestration happen later, in a worker process.
  Redis plays two independent roles here — message broker/result backend
  for Celery, and a cache for LLM-generated regex patterns — see
  [below](#asynchronous-processing-celery--redis) for why that's safe to
  share on one Redis instance.
- **PySpark** is the actual transformation engine. `regexp_replace` runs as
  a column expression across partitions, not a Python loop over rows, so
  the same code path that works for a 100-row CSV also works for a
  10-million-row one — only the number of partitions and runtime change.
- **Next.js** polls the status endpoint every 2s and renders a progress bar
  driven by the same `progress` value the worker is writing, then swaps to
  a paginated results table once the job succeeds.

## Repository layout

```
rhombus-ai-oa/
├── backend/                      # Django project
│   ├── api/
│   │   ├── models.py             # ProcessingJob (status, progress, inputs, result)
│   │   ├── views.py              # upload / status / cancel / paginated results
│   │   ├── tasks.py              # the one Celery task that does all the work
│   │   ├── middleware.py         # RequireAccessKeyMiddleware (shared-secret gate)
│   │   └── services/
│   │       ├── llm.py            # NL -> regex via Gemini, + safety validation
│   │       └── spark.py          # the actual Spark transformation + chunked write
│   ├── core/                     # settings.py, urls.py, celery.py
│   └── Dockerfile
├── frontend/                      # Next.js app
│   ├── app/page.tsx               # top-level form + polling state machine
│   ├── components/                # FileDropzone, ExtractionForm, ResultsTable
│   ├── lib/api.ts                 # apiFetch() — base URL + access-key header
│   ├── middleware.ts              # HTTP Basic Auth gate on the whole site
│   └── Dockerfile
├── docker-compose.yaml            # redis, web, worker, spark, spark-worker, frontend
├── .env.example                   # root-level config (Django, access gate, frontend)
└── backend/.env.example           # backend-only config (GOOGLE_API_KEY, local dev)
```

## Setup & run (Docker Compose)

**Prerequisites:** Docker + Docker Compose, and a Google Gemini API key
(the LLM step uses `langchain-google-genai`).

1. **Configure environment variables.** There are two separate `.env` files
   because of how they're consumed:

   - `.env` (repo root) — copy from `.env.example`. Read by
     `docker-compose.yaml`'s `environment:` blocks (Django security
     settings, the access-gate key, frontend build args).
   - `backend/.env` — copy from `backend/.env.example`. The `web` and
     `worker` services bind-mount the whole `backend/` folder into the
     container, so this file lands at `/app/.env` inside them and is picked
     up automatically by `python-dotenv`'s `load_dotenv()` in
     `core/settings.py`. **`GOOGLE_API_KEY` must go here**, not in the root
     `.env` — there's no explicit passthrough for it in
     `docker-compose.yaml`.

   ```bash
   cp .env.example .env
   cp backend/.env.example backend/.env
   # edit backend/.env and set GOOGLE_API_KEY=<your Gemini key>
   ```

   For a first local run, the defaults in `.env.example`/`backend/.env.example`
   (`DJANGO_DEBUG=True`, no access key) are enough — you only need to fill
   in real values for [deployment](#deployment-notes).

2. **Bring the whole stack up with one command:**

   ```bash
   docker compose up --build
   # or: make build
   ```

   This starts, in order of dependency: `redis`, `web` (Django on `:8000`),
   `worker` (Celery), `spark` (master) + `spark-worker`, and `frontend`
   (Next.js on `:3000`).

3. **Apply database migrations** (first run only, in a second terminal):

   ```bash
   docker compose exec web python manage.py migrate
   ```

4. Open **http://localhost:3000**.

To run the backend directly on the host instead (e.g. for faster
iteration), see `backend/Makefile` (`make db-migrate`, etc.) — you'll need
`uv`, a local Redis, and a local Spark master, so Docker Compose is the
easier path.

## Using the app

1. Drop a `.csv`, `.xls`, or `.xlsx` file onto the upload area. It's
   uploaded immediately and its real column names come back for a
   **dropdown** — no need to remember/retype a column name.
2. Pick the target column from that dropdown, describe the pattern in plain
   English (e.g. *"Find email addresses and replace them with 'REDACTED'"*),
   and enter the replacement value.
3. Submit — you immediately get a live progress bar (the file itself was
   already uploaded in step 1, so this step is instant).
4. Once the job succeeds, a paginated table of the processed data appears.
   You can cancel a running job at any time from the same screen.

Under the hood this is two API calls, not one, specifically so a large file
is only ever transferred to the server once:

- `POST /api/upload/` — stores the file, creates a `ProcessingJob` in
  `DRAFT` status, and returns its column names (`services/columns.py` reads
  just the header row — the first physical line for CSV, no dependency on
  Polars scanning/inferring the rest of the file).
- `POST /api/submit/<job_id>/` — attaches the column/prompt/replacement the
  user picked to that same `DRAFT` job and is the point where it actually
  transitions to `QUEUED` and gets handed to Celery.

## Asynchronous processing: Celery + Redis

**Broker & result backend.** Both are the same Redis instance, logical
database `0`, configured in `backend/core/settings.py`:

```python
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
```

The LLM-regex **cache** deliberately uses a *different* logical database
(`redis://redis:6379/1`, via `django-redis` in `CACHES`) on the same Redis
container. Same process, same container, zero extra infrastructure — but a
cache flush (`cache.clear()`) can never wipe out in-flight Celery task
state, and vice versa.

**The one Celery task.** `process_file_task` (`backend/api/tasks.py`) does
everything the web process is not allowed to do inline: it looks up the
`ProcessingJob`, resolves the regex (cache-or-LLM), converts Excel to CSV
via Polars if needed, and calls into `process_data_with_spark`. The web
process's only job is creating/updating the `ProcessingJob` row and, once
the user has picked a column and described the pattern (see
[Using the app](#using-the-app)), calling `process_file_task.apply_async(...)`
— reading the header row for the column dropdown in `upload_file()` is the
one synchronous file touch the web process does, and it's bounded to a
single line, never the whole file.

**Progress reporting.** The Celery task ID is pinned to the job's UUID
(`apply_async(args=[job.id], task_id=str(job.id))` in `views.py`) so the
polling endpoint can look up that exact task's live state later via
`AsyncResult(str(job.id))`. Progress moves through three bands:

| Stage                          | `job.progress` |
|---------------------------------|-----------------|
| Job picked up by a worker       | 10% |
| Regex resolved (cache or LLM)   | 30% |
| Spark rows processed            | 50% → 95%, scaled to `rows_processed / total_rows` |
| Job complete                    | 100% |

Row-level progress comes from `services/spark.py`: the DataFrame is
repartitioned into `NUM_PROGRESS_CHUNKS` (10) pieces, each chunk is written
separately, and a `progress_callback(rows_processed, total_rows)` fires
after every chunk. The Celery task turns that into both a `job.progress`
database write (for the simple `progress` field the UI already polls) and a
richer `self.update_state(..., meta={...})` call, which `check_status()`
surfaces as `progress_detail` while the job is `RUNNING` — so the frontend
could show "Processed 420,000/1,000,000 rows (42%)" if it wants finer detail
than the plain percentage.

**Failure, retries, cancellation.**
- `@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)`
  retries on failure with exponential backoff. We deliberately kept this
  broad (any `Exception`) rather than narrowing it to transient errors —
  see [trade-offs](#trade-offs--known-limitations) for the reasoning.
- Cancellation (`cancel_job` view) calls
  `current_app.control.revoke(task_id, terminate=True, signal="SIGKILL")`,
  which kills the worker process outright (needed because a Spark job stuck
  in the JVM won't respond to a polite Celery revoke) and marks the job
  `FAILED` with an explanatory message.

## Distributed processing: PySpark

`services/spark.py` reads the CSV with `spark.read.csv(...)`, applies
`regexp_replace` as a **column expression** via `withColumn` — this runs
inside Spark's Catalyst engine across however many partitions the
DataFrame has, not as a Python `for` loop over collected rows — and writes
the result back out as Parquet.

**Partitioning choice.** After counting rows once (`df.count()`, needed
anyway for progress reporting), the transformed DataFrame is explicitly
repartitioned to `NUM_PROGRESS_CHUNKS = 10` partitions
(`min(10, max(1, total_rows))` so tiny files don't get split into
mostly-empty partitions). Each partition is written as its own Parquet
chunk (`spark_partition_id() == chunk_id`, first chunk `overwrite`, the
rest `append`), and a progress callback fires after each one. This is a
deliberate trade-off: **10 fixed chunks keep progress reporting predictable
regardless of file size** (roughly even 10%-of-rows increments), at the
cost of not auto-tuning partition count to cluster resources the way you
would in a general-purpose Spark job. For genuinely large inputs (millions
of rows) this still parallelizes real work across `spark.cores.max`
executor cores — the constant only controls how many *write actions* and
progress updates happen, not how much data any one task holds in memory at
once, since each write is itself still a distributed Spark write over that
partition's rows.

Reading back for the UI (`get_paginated_results` in `views.py`) uses
`polars.scan_parquet(...)` — a **lazy** scan over the whole chunked output
directory — then `.slice(offset, limit).collect()` to materialize only the
one page actually requested. This is what keeps "millions of rows" from
ever hitting the browser: the full result set lives on disk as Parquet,
and only ~50 rows at a time are ever loaded into memory or serialized to
JSON.

Spark itself runs as two extra Compose services (`spark`, `spark-worker`),
each memory-capped (512M / 1G) and resource-limited via `spark.cores.max`
in the session config, so a single job can't starve the rest of the stack
on a small Droplet.

## LLM integration & regex safety

`services/llm.py` uses `langchain-google-genai` (Gemini) with a small
few-shot prompt to turn a natural-language description into a raw regex
string. That output is never trusted as-is — `validate_regex()` runs two
checks before it's cached or handed to Spark:

1. **Syntax validity** — `re.compile(pattern)`; a `re.error` is turned into
   a descriptive `ValueError` that surfaces as the job's `error_message`.
2. **Catastrophic-backtracking (ReDoS) guard** — the compiled pattern is run
   against a handful of adversarial probe strings (long repeated
   characters, deliberately-non-matching suffixes — the classic shapes that
   blow up patterns like `(a+)+$` or `([a-zA-Z]+)*$`), each under a
   500ms wall-clock timeout (`SIGALRM`-based). If any probe doesn't resolve
   in time, the pattern is rejected outright instead of ever reaching
   Spark, where it would otherwise be free to peg a CPU core indefinitely
   against real user data.

Only patterns that pass both checks get cached in Redis
(`regex_prompt_<normalized prompt>`, 24h TTL) and applied to the data.

## Large-file / scale testing

*To be filled in once a sizeable dataset has been run through the pipeline.*

Planned methodology:

1. Generate or source a CSV in the multi-million-row range (a synthetic
   dataset of names + emails works well since it exercises the same regex
   used in the example scenario).
2. Upload it through the running stack and record: total rows, wall-clock
   time from `QUEUED` to `SUCCESS`, and the `job.progress` cadence observed
   while it ran.
3. Confirm the paginated results endpoint stays fast (single-page fetch
   time) regardless of total row count, since it never materializes more
   than one page of Parquet at a time.

| Rows | File size | End-to-end time | Notes |
|------|-----------|------------------|-------|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ |

## Deployment notes

The app is deployed on a bare DigitalOcean Droplet IP (no domain/TLS yet).
Two independent access controls gate it, since there's no full user-account
system:

- **`RequireAccessKeyMiddleware`** (`backend/api/middleware.py`) — every API
  request must carry `X-Access-Key: <APP_ACCESS_KEY>`. The frontend attaches
  it automatically via `lib/api.ts` once `NEXT_PUBLIC_APP_ACCESS_KEY` is set
  at build time. No-ops entirely if `APP_ACCESS_KEY` is unset.
- **HTTP Basic Auth** (`frontend/middleware.ts`) — gates the site itself,
  driven by `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD`, read at request time
  (a plain container restart picks up changes, no rebuild needed).

See `.env.example` for the full list of deployment variables and inline
notes on which are build-time vs. runtime.

`DJANGO_DEBUG` is currently `True` on the live deployment while
functionality is being verified end-to-end; it must be flipped to `False`
(along with setting a real `DJANGO_SECRET_KEY` and `APP_ACCESS_KEY`) before
treating the deployment as final.

## Trade-offs & known limitations

- **Single target column.** The rubric's "target column(s)" phrasing allows
  for multi-column support, but the model, API, and UI here all take a
  single column name. This was a deliberate scope decision for this
  submission rather than an oversight — extending `ProcessingJob.target_column`
  to a comma-separated list and looping the `withColumn` call in
  `services/spark.py` would be the natural extension if needed.
- **Broad retry policy.** `autoretry_for=(Exception,)` retries permanent
  failures (a malformed upload, a genuinely unsafe regex) exactly as
  eagerly as transient ones (a Redis blip). We chose not to narrow this for
  this submission; a follow-up would split out a `PermanentFailure`
  exception type that bypasses retries entirely.
- **SQLite for job state.** Fine for a single-Droplet demo; a real
  multi-worker production deployment would move `ProcessingJob` to Postgres
  to avoid SQLite's single-writer lock under concurrent job updates.
- **No automated tests yet** for the Celery task or Spark service layer
  (`backend/api/tests.py` is currently a stub) — the pipeline has been
  verified manually end-to-end instead.
- **Orphaned `DRAFT` jobs.** If a user uploads a file (step 1 above) and
  then abandons the page without ever submitting or picking a different
  file, that `DRAFT` row and its uploaded file are never cleaned up. A real
  deployment would add a periodic task (Celery beat, or a simple cron'd
  management command) to delete `DRAFT` jobs older than, say, 24 hours.
