"""Reproducible policy-wide deterministic scenarios, separate from model accuracy."""
from datetime import datetime, timezone
import json
from .controller import ReviewController
from .policy import HORIZONCARE, ingest_policy


def run_service_evaluation(samples_dir, policy_dir, cache_dir, output_dir):
    cases=json.loads((samples_dir/'manifest.json').read_text())
    reviewer=ReviewController(policy_dir,cache_dir)
    index=ingest_policy(HORIZONCARE,policy_dir,cache_dir).index
    chunks={c.chunk_id:c for c in index.chunks}
    results=[]
    for case in cases:
        source=json.loads((samples_dir/case['file']).read_text())
        decision=reviewer.review(source)
        passed=decision.action==case['expected_action']
        if 'expected_payment' in case:
            passed &= decision.arguments.model_dump().get('payment_in_dollars')==case['expected_payment']
        passed &= set(case.get('expected_unresolved',[])) <= set(decision.context.unresolved_information)
        for evidence in decision.context.policy_evidence:
            evidence.validate_against(chunks[evidence.chunk_id])
        results.append(dict(case=case,input=source,passed=bool(passed),decision=decision.model_dump(mode='json')))
    report=dict(recorded_at=datetime.now(timezone.utc).isoformat(),mode='offline-services',
                passed=all(r['passed'] for r in results),correct=sum(r['passed'] for r in results),total=len(results),cases=results)
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'services-results.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Policy-wide service evaluation','',f"Passed: {report['correct']}/{report['total']}.",
           'Synthetic trusted assessments; this is not a clinical or model-accuracy benchmark.','',
           '| Case | Expected | Actual | Pass |','| --- | --- | --- | --- |']
    lines.extend(f"| {r['case']['file']} | {r['case']['expected_action']} | {r['decision']['action']} | {r['passed']} |" for r in results)
    (output_dir/'services-results.md').write_text('\n'.join(lines)+'\n')
    return {k:v for k,v in report.items() if k!='cases'}
