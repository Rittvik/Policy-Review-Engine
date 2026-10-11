# Synthetic reviewer walkthrough

Run these commands from the repository root. Every claim, document, assessment,
identity and benefit calculation in this directory is synthetic. Trusted
assessments are supplied in the JSON; neither the CLI nor the LLM establishes them.
Candidate extraction remains advisory and never changes the decision.

## Setup and ordinary reviews

```sh
uv sync --locked --extra dev
uv run --locked python -m claims_agent.cli ingest-policies
uv run --locked python -m claims_agent.cli review --input examples/covered_mri.json --format human
uv run --locked python -m claims_agent.cli review --input examples/missing_document.json
uv run --locked python -m claims_agent.cli review --input examples/high_value.json
uv run --locked python -m claims_agent.cli review --input examples/covered_payment.json
```

Expected walkthrough behavior: approve pre-authorization; request missing
documentation; route the high-value claim to senior review; approve payment of
900 dollars from the supplied trusted calculation. All actions are stubs.
These walkthrough expectations do not replace the separately planned evaluation.

## Advisory extraction without a key

```sh
uv run --locked python -m claims_agent.cli review --input examples/covered_mri.json --llm mock --llm-fixture examples/covered_mri_candidates.json --document NOTE --document HISTORY --format human
```

The fixture is a prewritten model response, not an LLM run. It is bound to the
exact example and policy revision. Modifying the input can invalidate it.
Human output labels candidates as untrusted and shows quotations. Default JSON
output contains `cli_schema_version`, `decision`, `advisory`, and `persistence`.

## Optional Gemini

```sh
uv sync --locked --extra dev --extra gemini
uv run --locked --extra gemini python -m claims_agent.cli review --input examples/covered_mri.json --llm gemini --document NOTE --document HISTORY --preview-llm-input
```

Preview exposes the exact instruction, selected text and response schema without
calling Gemini or saving a review. It needs no key. To make a live request,
configure `GEMINI_API_KEY` locally and remove `--preview-llm-input` from that
command. This transmits selected synthetic clinical text and policy excerpts to
Google. Review the README's data-use, pricing and quota notes first. The six live
evaluation cases passed with Gemini 3.5 Flash-Lite after resolving model/key issues
and avoiding the overloaded Flash model. See [live verification](../evaluation/live-verification.md).

A key alone does not enable a model call. Missing credentials, quota failures or
invalid model responses leave the deterministic decision available and report
an unavailable/invalid advisory status. JSON never reports such output as valid
clinical evidence. Only pre-authorization/payment extraction is supported.

## Persisted denial and appeal

Use a fresh database path for each complete walkthrough. Existing review IDs are
immutable and cannot be overwritten. The following uses `.review-history/demo.sqlite3`:

```sh
uv run --locked python -m claims_agent.cli review --input examples/appeal_original_denial.json --save --store .review-history/demo.sqlite3
uv run --locked python examples/prepare_appeal.py --store .review-history/demo.sqlite3 > .review-history/prepared_appeal.json
uv run --locked python -m claims_agent.cli appeal --input .review-history/prepared_appeal.json --store .review-history/demo.sqlite3 --format human
```

The first command saves a synthetic experimental-service denial. The helper
checks that the database record matches the template's denial in every field
except its runtime save timestamp, then copies the actual stored prior snapshot
into each appeal assessment request. It prints a new input and never edits the
store or any finding. If the saved denial differs, preparation fails. This is a
synthetic-demo helper, not a general assessment-rebinding facility.

The last command reviews newly supplied evidence and saves a linked approval.
Passing the static template directly cannot substitute for the saved snapshot.
Repeating the same appeal ID fails persistence; select a fresh database path to
restart the walkthrough. A save timestamp is never used as the denial-notice date.

## Commands and exit codes

`--policy-dir`, `--cache-dir`, and `--format json|human` are available on all
commands. Ordinary `review` persists only with `--save`; `appeal` uses the existing
automatic persistence after verified linkage. Both accept `--store`.
`--preview-llm-input` cannot be combined with `--save`.

Exit 0 means a completed review, including a denial, missing-document request or
senior routing. Exit 2 means invalid arguments/input or an unreadable input file.
Exit 1 means an operational error, including failed persistence. Optional advisory
unavailability does not turn a completed deterministic review into a command failure.
JSON data goes to stdout; argparse and library diagnostics go to stderr.

```sh
uv run --locked --extra dev python -m pytest tests/test_cli.py -q
```

## Reviewer-confirmed extraction

The [confirmation workflow](clinical_review/README.md) demonstrates actual Gemini extraction,
explicit synthetic reviewer assessment and a new deterministic decision.
Ordinary extraction remains advisory until that assessment is supplied.
