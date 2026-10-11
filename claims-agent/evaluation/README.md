# Labelled synthetic evaluation

Run from the repository root:

```sh
uv run --locked python -m claims_agent.cli evaluate
```

This runs 20 decision/boundary cases and six extraction cases **offline**. It
writes `evaluation/results.md` and `evaluation/results.json`. Re-running offline
evaluation replaces those two latest-result files. Use `--output-dir` to retain
another run. A failed expectation exits 1; malformed configuration exits 2.

`decision_cases.json` freezes actions, arguments, evidence sections and relevant
missing/unresolved indicators. `extraction_cases.json` freezes topic statuses and
exact supporting quotation anchors. Inputs are in `cases/` and `extraction/`.
Prewritten mock responses are separate files: changing labels does not regenerate
the response or automatically turn a failure into a pass.

All inputs are synthetic. Decision cases include trusted supplied assessments.
D09 injects one foreign-policy chunk in an isolated sequential runner; it adds no
fault-injection option to the ordinary review command. D17/D18 use temporary
SQLite stores and bind matching saved prior snapshots to their runtime timestamps.
No reviewer database is modified. D19/D20 test model failures alongside complete
trusted inputs; the model is not responsible for those cases' approvals.

D11 expects senior review because the supplied PDF does not resolve the screening
exception. It does not fabricate a preventive exclusion. D18 follows the approved
appeal behavior: unestablished relevant new evidence routes to senior review.

## Scoring

Decision scoring checks exact actions and critical arguments, exact missing-item
sets, required unresolved indicators, expected policy sections, all emitted policy
and document quotations, the action schema, and immutable linked appeal persistence.
Grounding scores exclude three no-source/foreign-source cases from the source-case
denominator; those cases are checked separately for absence of foreign citations.

Extraction scoring checks local schema/provenance validation, all 24 topic labels,
and 14 supporting quotation anchors across six cases. A longer exact quotation can
contain an anchor; invented or misattributed quotes fail local validation. Missing,
invalid, or unavailable responses remain in the denominator. There is no semantic
similarity or LLM judge. Matching a quote does not prove clinical truth or sound
interpretation; live statements still need human inspection.

Offline extraction scores verify the mock harness, **not Gemini performance**.
The report explicitly records live Gemini as `not_run`.

## Live request preview

The exact prepared calls are in `live-preview/L01.json` through `L06.json`.
`live-preview/manifest.json` records their input and file hashes. Each call has
three strings: instruction, payload JSON and response-schema JSON. To regenerate
previews, select a new directory (existing directories are not overwritten):

```sh
uv run --locked python -m claims_agent.cli evaluate --preview-llm-input --output-dir /tmp/claims-preview-new
```

Preview needs no model key and makes no external calls. Payloads contain selected
synthetic notes, requested topics, codes, workflow, request binding and policy
excerpts. Structured patient/member/provider IDs and payment values are omitted.
For L06, malicious claim notes are intentionally included as untrusted test data.

## Live Gemini run

The first six-request run was approved and attempted on 2026-10-09. All six
returned unavailable, so no live extraction quality was established. See
[the preserved attempt report](gemini-20261009T080546266271Z.md). The original
adapter masked provider failures behind one generic code, so that report cannot
distinguish quota, access, connection or request errors. The adapter now returns
allowlisted error categories without provider messages or credentials.

The user subsequently authorized completing the integration. Diagnostics found
HTTP 404 for the legacy model, followed by HTTP 403 reporting a leaked key on the
replacement model. After the user replaced the key, Gemini 3.8 Flash succeeded
on L01 but returned server errors on the other five cases; a follow-up confirmed
HTTP 503 high demand. Switching explicitly to Gemini 3.5 Flash-Lite produced a
complete six-case pass. See [live verification](live-verification.md).

After approving the exact payloads and configuring `GEMINI_API_KEY` locally:

```sh
uv run --locked --extra gemini python -m claims_agent.cli evaluate --mode gemini
```

For a local key file, add `--env-file /path/to/.env` to `uv run`. This file is
not read automatically by the application. Do not include it in the submission.

This explicitly selects the real adapter and runs **only the six extraction
cases**, with bounded exponential backoff retries for transient provider errors (HTTP 429 rate limit, 5xx, timeouts, connection drops) using `RetryInfo` delay handling. It sends the policy
excerpts to Google as well as synthetic clinical text. Free-tier access/quotas
must be checked for your project; the adapter cannot guarantee billing status.
No account or billing configuration is changed by this application.

Timestamped `gemini-*.json` and `gemini-*.md` reports preserve each live attempt
without overwriting offline results. Failed/unavailable results are retained as
failures; `attempted` does not imply six successful remote responses. Responses
that fail validation are recorded as sanitized failure results, not raw provider
bodies. Six cases are a demo check, not a population accuracy estimate.

For harness and regression verification without Google access:

```sh
uv run --locked --extra dev --extra web --extra gemini python -m pytest tests/ -v
```

## System Audit & Remediation Suite (182 Checks)

The repository includes a comprehensive 182-check verification audit suite:
- [Audit Remediation Report](audit-20261011-remediation/report.html): **182/182 checks passed (100% pass rate)** with 0 failures and 0 unavailable cases across all 17 policy categories, API persistence, readback, CLI execution, boundary checks, and 28 live Gemini calls.
- Run locally with:
  ```sh
  uv run --locked --extra dev --extra web --extra gemini python scripts/audit_system.py
  uv run --locked --extra dev --extra web --extra gemini python scripts/audit_boundaries.py
  ```

## Reviewer-confirmed extraction

The [confirmation workflow](reviewer-confirmation.md) demonstrates actual Gemini extraction,
explicit synthetic reviewer assessment and a new deterministic decision.
Ordinary extraction remains advisory until that assessment is supplied.
