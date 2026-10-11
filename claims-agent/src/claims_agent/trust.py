"""Versioned provenance rubric, never a probability or decision input."""

RUBRIC = 'evidence-reliability-v1'
LIMITATION = ('Measures input binding and traceable quotations, not whether quotations entail '
              'a finding or whether a clinical interpretation is correct. Human review is required.')


def evidence_reliability(result, prepared=None, *, origin='live_adapter'):
    from .llm import validate_response
    score = dict(rubric=RUBRIC, origin=origin, score=None, maximum=100,
                 limitation=LIMITATION, findings=[], components={}, state='no_output')
    if result.status == 'unavailable':
        return score
    score.update(score=0, state='rejected')
    if result.status != 'validated_candidates' or prepared is None:
        return score
    try:
        if result.input_sha256 != prepared.input_sha256 or result.request_id != prepared.payload.request_id:
            return score
        response = validate_response(result.candidates.model_dump_json(), prepared.payload)
    except (ValueError, AttributeError):
        return score
    for finding in response.findings:
        components = dict(schema_and_topics=20, input_binding=20,
                          document_provenance=40 if finding.document_refs else 0,
                          policy_provenance=20 if finding.policy_refs else 0)
        score['findings'].append(dict(topic=finding.topic, score=sum(components.values()),
                                     components=components, absence_verified=False if finding.status == 'not_found' else None))
    score.update(state='provenance_checked', score=round(sum(f['score'] for f in score['findings']) / len(score['findings']), 1))
    score['components'] = {k: round(sum(f['components'][k] for f in score['findings']) / len(score['findings']), 1)
                           for k in score['findings'][0]['components']}
    return score
