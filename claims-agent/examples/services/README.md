# Policy-wide service demonstrations

All claims, clinicians, equipment costs, benefit determinations and formularies
here are **synthetic**. `manifest.json` lists 23 expected outcomes. The deterministic
examples include all service families in the supplied policy and boundary cases.

```sh
uv run --locked python -m claims_agent.cli evaluate-services
uv run --locked python -m claims_agent.cli review --input examples/services/mri-brain.json --format human
uv run --locked python -m claims_agent.cli review --input examples/services/ct-emergency.json --format human
uv run --locked python -m claims_agent.cli review --input examples/services/dme-exactly-500.json --format human
uv run --locked python -m claims_agent.cli review --input examples/services/dme-over-500-no-auth.json --format human
uv run --locked python -m claims_agent.cli review --input examples/services/drug-formulary-missing.json --format human
```

DME at exactly $500 needs no PA; $500.01 does. That exception never establishes
medical necessity or a payable amount. Drug examples that approve include an
explicit synthetic formulary; the supplied policy alone cannot identify covered
drugs. See [policy coverage](../../docs/policy-coverage.md) for the complete matrix.

## Actual CT Gemini extraction, with offline replay

`ct-review.json` has no clinical assessment. `ct-extraction.json` records a real
Gemini call on 2026-10-09. It returned documented diagnosis support, necessity and
emergency status with exact quotations. `ct-packet.json` preserves the source and
policy binding. `ct-reviewer-template.json` is deliberately incomplete.
`ct-reviewer-response.json` is an explicitly completed **synthetic** reviewer
fixture, not a real clinical sign-off. Its new saved decision is in
`ct-reviewed-decision.json`: payment approval for the supplied $900 after all gates.

In the browser, load **CT — Clinical assessment needed**, choose **Recorded Gemini
demo**, leave NOTE selected and HISTORY unselected, then run review. Inspect the
note and policy, enter a reviewer label, assess the three predicates, supply
reasons, explicitly carry forward coding/exclusion/payment assessments, and confirm.
The new decision and original review appear in linked history.

To reproduce the recorded fixture from the CLI, use a new store:

```sh
uv run --locked python -m claims_agent.cli review-assessment --packet examples/services/ct-packet.json --assessment examples/services/ct-reviewer-response.json --store .review-history/ct-demo.sqlite3 --format human
```

To make a new call using your own local key:

```sh
uv run --locked --extra gemini --env-file .env python -m claims_agent.cli review --input examples/services/ct-review.json --llm gemini --document NOTE --preview-llm-input
uv run --locked --extra gemini --env-file .env python -m claims_agent.cli review --input examples/services/ct-review.json --llm gemini --document NOTE > ct-fresh-extraction.json
```

Prepare a fresh packet/response using `prepare-assessment` and complete it as in
the [confirmation walkthrough](../clinical_review/README.md). Do not reuse a
completed response against a different packet. The application never supplies
clinical verdicts automatically. Live availability and interpretation can vary.

`build_service_samples.py` regenerates deterministic synthetic fixtures only.
It does not generate or replace the recorded Gemini response or reviewer sign-off.
