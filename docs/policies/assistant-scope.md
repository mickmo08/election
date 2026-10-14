# Research assistant scope and controls

* Read-only tools (`services/assistant/tools.py`) on the caller's RLS-scoped session; numbers computed in code.
* Every material number must appear in tool evidence and its sentence must cite an evidence id; answers failing
  the grounding check are replaced by the deterministic composer (recorded as `fallback_used`).
* Evidence kinds are labelled: official result, poll, model estimate, public-discussion frequency, registry.
* Warnings for synthetic, stale, preliminary, disputed or missing evidence are returned with every answer.
* Refusals: individual profiling (beliefs/religion/ethnicity/vote of named people), persuasion/targeting/outreach,
  inferring ballot choices from turnout records, race calls.
* Budget: max 6 tool calls, 1,200 output tokens, provider timeout 30 s, per-user rate limit, monthly AI quota.
* Providers: Anthropic Claude via the official SDK (default model `claude-opus-5-5`, server-side refusal
  fallbacks), any OpenAI-compatible endpoint, and an offline deterministic provider used when none is configured.
* Reproducibility: question, provider, model, prompt version, tool calls + arguments, evidence, warnings,
  grounding result, tokens and latency are stored per query.
* Evaluation: `backend/evals/assistant_eval.py` (see readiness matrix for current results and limitations).
