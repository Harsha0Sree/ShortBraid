"""
Prometheus metrics (Day 9).

Counters   — monotonically increasing (request count, tokens saved)
Histograms — bucketed distributions (latency, payload size)
Gauges     — point-in-time values (in-flight requests, queue depth)
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

# Use a fresh registry so test runs don't pollute the default
REGISTRY: CollectorRegistry = CollectorRegistry()

# --- LLM-specific ---
llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API calls made (post-cache).",
    ["model", "endpoint"],
    registry=REGISTRY,
)

tokens_saved_total = Counter(
    "tokens_saved_total",
    "Tokens saved by the semantic cache.",
    ["endpoint"],
    registry=REGISTRY,
)

llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Cumulative USD spent on LLM API calls.",
    ["model"],
    registry=REGISTRY,
)

# --- API-specific ---
api_requests_total = Counter(
    "api_requests_total",
    "Total HTTP requests handled.",
    ["endpoint", "method", "status"],
    registry=REGISTRY,
)

api_latency_seconds = Histogram(
    "api_latency_seconds",
    "HTTP request latency in seconds.",
    ["endpoint", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

cache_hits_total = Counter(
    "cache_hits_total",
    "Semantic cache hits.",
    ["endpoint"],
    registry=REGISTRY,
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Semantic cache misses.",
    ["endpoint"],
    registry=REGISTRY,
)

rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total",
    "Requests rejected by the rate limiter.",
    ["endpoint"],
    registry=REGISTRY,
)

# --- Infra ---
in_flight_requests = Gauge(
    "in_flight_requests",
    "Currently in-flight HTTP requests.",
    registry=REGISTRY,
)

queue_depth = Gauge(
    "queue_depth",
    "Number of jobs waiting in the arq queue.",
    registry=REGISTRY,
)

db_pool_in_use = Gauge(
    "db_pool_in_use",
    "DB connections currently checked out.",
    registry=REGISTRY,
)
