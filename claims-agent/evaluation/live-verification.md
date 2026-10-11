# Live Gemini verification — 2026-10-09

**The real Gemini integration works. All six synthetic extraction cases passed
with `gemini-3.5-flash-lite`.** These responses came from Google's API, not mocks.

[Full live report](gemini-20261009T082044064385Z.md) ·
[Inputs, labels, returned findings and timings](gemini-20261009T082044064385Z.json)

| Check | Result |
| --- | --- |
| Responses passing schema and exact-source validation | 6/6 |
| Expected topic statuses | 24/24 |
| Supporting quotation anchors | 14/14 |
| Per-request elapsed time in this run | 2.05–2.77 seconds |

Cases cover explicit support, treatment contraindication, missing information,
conflicting necessity statements, irrelevant documents, and injected instructions
in claim notes. Inspection of the returned statements found them consistent with
the supplied assertions: the conflict case cited both opposing notes, absent topics
remained not_found, and the injection case did not invent an approval or evidence.
This is a small synthetic check, not a clinical validation or general accuracy claim.

The L01 smoke response was reused in the report; L02–L06 were then called once each.
No successful response was substituted for a failure from another model. The
previous model's failed run remains a separate report. The prompt, payloads and
labels were unchanged across the live model comparison.

## What the LLM now does

Gemini reads the selected clinical documents and retrieved policy excerpts, then
returns candidate findings with exact document/policy quotations. Local code
validates those sources and presents the findings as advisory output. It does not
promote them into trusted assessments, approve claims, compute payments, or bypass
missing evidence. The deterministic decision remains a separate output.

For example, the live response to “Conservative treatment was attempted.” reported
that treatment was documented and quoted that exact sentence. It reported
contraindication as not_found when the document said nothing about it.

## Earlier failures and resolution

1. Initial Gemini 2.5 Flash requests were unavailable. A diagnostic later confirmed
   HTTP 404 because that model was unavailable to new users.
2. Gemini 3.8 Flash returned HTTP 403 reporting that the original key was leaked.
   The user replaced the key locally.
3. With the replacement key, Gemini 3.8 Flash passed L01 but returned server errors
   on L02–L06. A subsequent L02 diagnostic returned HTTP 503 with a high-demand
   message. [Preserved partial run](gemini-20261009T081919194578Z.md).
4. An explicit switch to Gemini 3.5 Flash-Lite produced the complete six-case pass.
5. In the subsequent audit remediation, bounded exponential backoff retry with `RetryInfo` delay handling was implemented in `gemini.py`, resolving transient provider rate limits (HTTP 429) and server overloads across all 28 live test calls (100% pass rate in `evaluation/audit-20261011-remediation/report.html`).

Google documents Flash-Lite for simple data processing and currently lists a
free tier. Availability and quota remain project-specific:
[model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Reproduce

From the repository root, using the current local key location:

```sh
uv run --locked --extra gemini --env-file src/claims_agent/.env python -m claims_agent.cli review --input evaluation/extraction/L01.json --llm gemini --document NOTE1 --format human
```

Use your own local environment-file path if different. The input intentionally
has no trusted clinical assessments: expect a senior-review decision alongside
Gemini's extracted findings. This demonstrates actual extraction without claiming
that model findings have been clinically verified.

For all six live benchmark cases:

```sh
uv run --locked --extra gemini --env-file src/claims_agent/.env python -m claims_agent.cli evaluate --mode gemini
```

For the comprehensive 28 live-call system audit:

```sh
uv run --locked --extra gemini --env-file src/claims_agent/.env python scripts/audit_system.py --live --live-interval 5
```

Each command makes external requests. New results get timestamped filenames.
Provider availability and model output can vary. The key-free walkthrough and
141 passing local unit/integration tests remain available independently of Google's service.
