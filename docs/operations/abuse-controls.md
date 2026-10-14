# Abuse controls

| Control | Where | Setting |
|---|---|---|
| Per-IP rate limit (global) | AWS WAF rate-based rule | 2,000 requests / 5 min / IP (`waf_rate_limit_per_5min`) |
| Managed rule groups | AWS WAF | Common rule set (body-size rule in count mode; API enforces 25 MB), Known bad inputs |
| Per-instance token bucket | API (`ratelimit.py`) | `ELECTION_RATE_LIMIT_PER_MINUTE` (120) per client IP; returns 429 + Retry-After. Per-process, so effective limit scales with replicas — WAF is authoritative |
| Assistant limit | API | 10/min per user (burst 5) + monthly `ai_queries` quota (HTTP 402 when exhausted) |
| Quotas | `entitlements.py` | imports, exports, AI queries, storage bytes per plan; checked under an advisory lock to avoid races |
| Upload protection | `api/deps.py`, adapters | extension allow-list, content sniffing (zip magic, NUL bytes), 25 MB cap, zip-bomb expansion cap (600 MB), survey row cap 200k |
| LLM cost | providers | max tool calls 6, max output tokens 1,200, 30 s timeout, provider fallback, token metering |
