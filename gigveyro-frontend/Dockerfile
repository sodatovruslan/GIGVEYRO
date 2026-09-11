# ============================================================
# GIGVEYRO Frontend — Production Dockerfile
# Next.js 16, multi-stage (deps → builder → runner)
# Uses Next.js standalone output for minimal image
# ============================================================

# ---------- Stage 1: deps ----------
FROM node:20-alpine AS deps

WORKDIR /app

# Install dependencies only (cache layer)
COPY package.json package-lock.json ./
# The sanity check after npm ci matters: under a flaky network, npm can hit
# "Exit handler never called!" and still return exit code 0 with an
# incomplete node_modules, which otherwise only surfaces two stages later as
# a confusing "next: not found" in the builder stage.
RUN npm ci --frozen-lockfile && test -x node_modules/.bin/next

# ---------- Stage 2: builder ----------
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Next.js standalone output — enables minimal /app/.next/standalone image
# NEXT_TELEMETRY_DISABLED skips build-time telemetry
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

# ---------- Stage 3: runner ----------
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# Runtime port — override via env
ENV PORT=3000
# Docker sets HOSTNAME to the container ID for every container, and the
# Next.js standalone server binds to process.env.HOSTNAME if it's set -
# so without this override it silently listens only on the container's
# own address, refusing connections on localhost (breaks the
# HEALTHCHECK below) and is not reliably reachable from other
# containers such as nginx either.
ENV HOSTNAME="0.0.0.0"

RUN addgroup --system --gid 1001 nextjs \
    && adduser --system --uid 1001 nextjs

# Copy standalone output (smallest possible footprint)
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD wget -qO- http://localhost:3000/ 2>/dev/null || exit 1

# Server-side variables such as BACKEND_API_URL are injected at runtime.
# NEXT_PUBLIC_* values are build-time constants; production realtime defaults
# to the current same-origin wss:// endpoint and needs no public API variable.
CMD ["node", "server.js"]
