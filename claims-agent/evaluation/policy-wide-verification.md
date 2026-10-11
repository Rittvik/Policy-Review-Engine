# Policy-wide verification — 2026-10-09

The implementation now covers MRI across anatomical regions, CT, ultrasound,
office/specialist visits, outpatient procedures, emergency services, inpatient
admission, DME and drugs under the supplied policy. Unsupported facts/dependencies
remain explicit review cases. See the [coverage matrix](../docs/policy-coverage.md).

- **23/23 service scenarios passed**, including emergency CT, elective admission,
  DME $500/$500.01, specialty PA designation and missing formulary/cost evidence.
  [Detailed results](services-results.md) include complete inputs and decisions.
- **51/51 complete policy verification matrix cases passed (100.0%)** across all 17
  medical benefit categories testing Happy Path, Edge Case, and Definite Failure per category.
  [Full JSON archive](policy_verification_51_cases.json).
- The original **20/20 decision cases and 6/6 mock extraction cases** remain passing.
- A fresh actual Gemini CT request returned validated findings for all three
  requested topics. A deliberately completed synthetic reviewer response changed
  initial senior routing into a linked $900 payment approval; no PA was required
  because emergency status was explicitly established. [Recorded extraction](../examples/services/ct-extraction.json)
  and [confirmed result](../examples/services/ct-reviewed-decision.json).
- Tests exercise clinical/exclusion rules for each family, unknown classifications,
  stale DME evidence, source-typed formulary requirements, classification conflicts,
  missing applicable inputs, exact quote validation, service-specific review forms,
  shared priority gates, policy changes and saved appeals across multiple families.

These examples demonstrate software behavior, not real-world medical sufficiency,
formulary authenticity or a statistical accuracy guarantee. No real claim system
or funds are affected. All external-source fixtures are explicitly synthetic.
