FROM oven/bun:1 AS builder
WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, so
# they must be passed as build args (not just runtime env vars) — see the
# `args:` block for the `frontend` service in docker-compose.yaml.
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_APP_ACCESS_KEY
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_APP_ACCESS_KEY=${NEXT_PUBLIC_APP_ACCESS_KEY}

RUN bun run build

FROM oven/bun:1 AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts

# BASIC_AUTH_USER / BASIC_AUTH_PASSWORD are read at request time by
# middleware.ts, so they're passed as normal runtime env vars (see
# docker-compose.yaml), not build args.

EXPOSE 3000
# Explicit -H 0.0.0.0 so the app is reachable through the Docker port
# mapping — don't rely on next start's default bind address.
CMD ["bunx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
