"""P4 coding-model providers. The async Solar provider adds resilience (timeouts, bounded retries with
backoff + jitter + Retry-After, circuit breaker, per-org/global concurrency), accounting, and redaction. The
provider never places the API key in exceptions, logs, artifacts, metrics, or audit events."""
