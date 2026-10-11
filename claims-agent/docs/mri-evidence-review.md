# MRI requirement-based retrieval review

Actual results from the supplied policy. This is a retrieval milestone, not a claim-decision evaluation.

| Requirement | Retained candidate sections | Candidate status | Assessment |
| --- | --- | --- | --- |
| eligibility | 2 Member Eligibility and Plan Status (p1) | candidates_found | unresolved |
| authorization | 3.1 Services Requiring Prior Authorization (p1) | candidates_found | unresolved |
| documentation | 3.2 Documentation Required (p2) | candidates_found | unresolved |
| mri_coverage | 5.1 MRI Coverage (p2) | candidates_found | unresolved |
| medical_necessity | 4 Medical Necessity Standard (p2) | candidates_found | unresolved |
| exclusions | 6 Exclusions (p2) | candidates_found | unresolved |
| screening_exception | 5.2 Non-Covered Imaging (p2) | candidates_found | unresolved |
| retroactive_authorization | 3.1 Services Requiring Prior Authorization (p1) | candidates_found | unresolved |

Combined output: 7 unique chunks. Missing candidate topics: [].

## Method and boundaries

The collector is now reusable: `retrieve_evidence` accepts an explicit checklist,
while `retrieve_mri_evidence` supplies `MRI_REQUIREMENTS` from `requirements.py`.
The MRI results below remain unchanged. A separate synthetic checklist confirms
that other requirements do not inherit MRI topics. Empty checklists, duplicate
keys, empty queries/gates, and malformed gate tokens are rejected. The current
full suite has 66 passing tests; the original 56-test milestone is recorded below.
No other service checklist or automatic workflow dispatch has been implemented.

Eight explicit lexical query templates cover eligibility, authorization,
documentation, MRI coverage, medical necessity, exclusions, screening exceptions,
and retroactive authorization. The last two split exceptions into separate
checks so finding a generic exclusion does not hide a missing exception.
These are workflow search definitions, not newly inferred coverage rules.

Each query records its initial top three hits, then expands across all matching
chunks in the selected policy revision. Expansion happens even when the initial
search found a candidate, to avoid suppressing additional qualifications or
contradictions. This small-policy implementation ranks in memory and scans all
candidates; large corpora would need a persistent lexical index and measured
retrieval limits.

Explicit token groups filter candidate section bodies; section numbers and
heading names are not lookup keys. A heading alone cannot satisfy a topic gate.
The result records rejected section identifiers. Related fragments of an accepted
section stay together across pages. The combined bundle deduplicates chunk IDs,
while preserving each requirement's evidence mapping.

## Observed results and tests

The eight expected topic-to-section mappings were retrieved exactly for this
policy: 8/8 expected mappings, with no off-topic section mappings retained in
this demonstration. This is a small, policy-specific regression result, not a
production precision/recall estimate. The broad-query baseline remains available
in `retrieval-review.md`.

56 tests passed across ingestion and retrieval. New tests remove each required
section and verify explicit missing-candidate reporting; inject an irrelevant,
keyword-heavy heading that outranks the correct section; rename/renumber sections;
split authorization and its exception across pages; retain a potentially
contradictory authorization provision; and reject a wrong policy or mixed source
revision. These are synthetic perturbations, not changes to the supplied PDF.

## Remaining limitations

Candidate availability is not evidence sufficiency. All assessments remain
`unresolved`; this module neither approves claims nor determines medical necessity.
The later controller must validate claim facts and the meaning of policy evidence,
handle contradictions, and route unresolved cases according to the approved rules.

Token gates can reject valid rewordings or accept irrelevant passages containing
all required terms. Even all-eight-topic coverage does not prove that every
applicable exception was found. A new topic or substantially changed wording
requires query/gate review and regression tests. There are no embeddings, inferred
synonyms, or LLM calls. This first bundle is MRI-specific; it does not claim to
cover CT, DME, appeals, or every check in the full claims workflow.

## Reproduce

```sh
uv run --locked --extra dev python - <<'PYTHON'
from pathlib import Path
from claims_agent.policy import ingest_policy, resolve_policy
from claims_agent.evidence import retrieve_mri_evidence

spec = resolve_policy("HorizonCare", "Silver PPO 2500")
index = ingest_policy(spec, Path("policies"), Path(".policy-cache")).index
bundle = retrieve_mri_evidence(index, insurer=spec.insurer, plan_name=spec.plan_name)
for result in bundle.requirements:
    print(result.requirement.key, result.status, result.assessment)
    print([(c.section, c.source_page) for c in result.chunks])
print("Missing candidate topics:", bundle.missing_requirements)
PYTHON
```
