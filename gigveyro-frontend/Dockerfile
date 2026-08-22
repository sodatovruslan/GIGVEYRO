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
RUN npm ci --frozen-lockfile

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

# Runtime env vars (NEXT_PUBLIC_* and server-side) are injected via Docker env,
# NOT baked into the image. See docs/deployment.md for env strategy.
CMD ["node", "server.js"]
