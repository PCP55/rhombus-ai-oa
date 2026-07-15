# Frontend

Next.js app for the Data Processor UI. See the [root README](../README.md) for
architecture, API endpoints, and Docker setup.

```bash
bun install
bun dev          # http://localhost:3000 (needs Django API on :8000)
```

Environment variables are baked in at build time via Docker (`NEXT_PUBLIC_*`).
For local dev the defaults in `lib/api.ts` point at `http://localhost:8000`.
