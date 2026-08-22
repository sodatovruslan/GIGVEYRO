"""
GIGVEYRO Infrastructure package.

Centralised infrastructure primitives:
  - redis_client      : async Redis connection pool + health
  - redis_rate_limiter: Redis-backed sliding-window rate limiter
  - logging_config    : structured JSON logging setup
  - metrics           : Prometheus metrics endpoint
  - sentry            : optional Sentry SDK initialisation
"""
