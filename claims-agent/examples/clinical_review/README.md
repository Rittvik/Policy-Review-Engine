# Gemini findings → reviewer assessment → new decision

All inputs and reviewer choices here are synthetic demonstrations, not an actual
clinical sign-off. `extraction.json` is a real Gemini 3.5 Flash-Lite response
recorded on 2026-10-09. Gemini identified three documented predicates and no
contraindication finding. The original decision remains `route_to_senior_reviewer`
because `source_claim.json` has no trusted clinical assessment.

`reviewer_response.json` explicitly establishes diagnosis support, medical necessity
and attempted treatment, while leaving contraindication unknown. It acknowledges
the existing synthetic coding, treatment-history applicability and exclusion
assessments. With those prerequisites satisfied, the new review returns
`approve_pre_authorization`. No model status is automatically mapped to a verdict.

## Reproduce without an API key

Run from the project root after README setup:

```sh
mkdir -p .assessment-review
uv run --locked python -m claims_agent.cli prepare-assessment --input examples/clinical_review/source_claim.json --extraction examples/clinical_review/extraction.json --document NOTE --document HISTORY --packet-output .assessment-review/packet.json --review-output .assessment-review/reviewer.json
uv run --locked python -m claims_agent.cli review-assessment --packet .assessment-review/packet.json --assessment examples/clinical_review/reviewer_response.json --store .review-history/clinical-demo.sqlite3 --format human
```

The second command deliberately uses the **completed synthetic example**, not the
pending form. Using `.assessment-review/reviewer.json` unchanged must fail with
exit code 2. Preparation refuses to overwrite files; applying a response refuses
to reuse its review ID. For a repeat demo, choose fresh output paths and a fresh
store, or explicitly choose a new review ID in a copy of the completed response.

The supplied `packet.json`, `reviewer_template.json` and `reviewed_decision.json`
show the generated packet, pending form and observed result. Recreating a packet
from the identical sources and extraction produces the same checksum.

## Use a fresh Gemini extraction

Install the Gemini extra and configure your own `.env` as described in the main
README. The first command below makes one external request using synthetic text.
Preparation and confirmation are local and make no model calls.

```sh
uv run --locked --extra gemini --env-file .env python -m claims_agent.cli review --input examples/clinical_review/source_claim.json --llm gemini --document NOTE --document HISTORY > .assessment-review/fresh-extraction.json
uv run --locked python -m claims_agent.cli prepare-assessment --input examples/clinical_review/source_claim.json --extraction .assessment-review/fresh-extraction.json --document NOTE --document HISTORY --packet-output .assessment-review/fresh-packet.json --review-output .assessment-review/fresh-reviewer.json
```

Read the fresh packet's full source documents, policy excerpts, model findings and
original decision. Edit `fresh-reviewer.json` to record your assessment:

- Set `reviewer_id`, timezone-aware `reviewed_at` (ISO 8601) and a unique `new_review_id`.
- Keep the generated `packet_sha256`; a fresh extraction can change it, so the
  bundled completed response cannot be assumed to match a new call.
- Assess all four findings in their existing order as `established`,
  `not_established`, `unknown` or `conflicting`, and supply a nonempty reason.
- Confirm, correct or reject suggested evidence. Evidence must contain an exact
  quote and document ID from the selected source documents. Established and
  not-established findings require evidence; conflicting findings need two
  distinct references. Unknown is not false. A quote alone does not prove
  clinical sufficiency; the reviewer must assess that.
- Explicitly list any still-current assessments in `carry_forward_assessments`.
  Preparation lists available fields. Unselected fields become unknown in the
  new review. Missing or stale selected assessments are rejected.
- Set `confirmed_sources` to true only after completing the source review.

Then run:

```sh
uv run --locked python -m claims_agent.cli review-assessment --packet .assessment-review/fresh-packet.json --assessment .assessment-review/fresh-reviewer.json --store .review-history/clinical-live.sqlite3 --format human
```

The application verifies sources and policy revision, creates a new clinical
assessment and reruns every applicable deterministic gate. It saves the original
review (if absent), new linked review, extraction packet and reviewer response
before returning the new decision. It never overwrites an existing review or an
existing clinical assessment. If saving the new review fails, no approval is
returned; the original may already have been saved and a retry remains possible.

This flow fills missing clinical assessments for MRI pre-authorization and payment.
Payment still needs authorization and a trusted payable amount. Appeals retain
their existing separate saved-denial/intake workflow. It is not a clinical-assessment
replacement tool or an automatic appeal submission.

Reviewer identity is a trusted local label. The checksum binds snapshots but is
not an authentication mechanism. Production would need authenticated reviewers,
permissions and protected audit storage. All actions remain local stubs.
