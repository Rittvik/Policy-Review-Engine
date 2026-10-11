"""Bind the synthetic appeal template to an identical denial saved in this demo.

Prints JSON to stdout. Does not change a stored review or any clinical finding.
"""
import argparse
from pathlib import Path

from claims_agent.appeals import AppealSubmission
from claims_agent.cli import read_json
from claims_agent.reviews import ReviewStore, ReviewStoreError


def prepare(store_path, template_path):
    template = AppealSubmission.model_validate(read_json(template_path))
    expected = template.request.prior_review
    actual = ReviewStore(store_path).get(expected.claim.review_id)
    if actual is None or actual.model_dump(exclude={'recorded_at'}) != expected.model_dump(exclude={'recorded_at'}):
        raise ValueError('Saved denial does not match the synthetic template')
    request = template.request.model_copy(update={'prior_review': actual})
    data = template.model_dump()
    data['request'] = request.model_dump()
    for key in ('timing_assessment', 'evidence_assessment'):
        if data[key] is not None:
            data[key]['request'] = request.model_dump()
    return AppealSubmission.model_validate(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--template', type=Path, default=Path(__file__).with_name('appeal_submission.json'))
    args = parser.parse_args()
    try:
        result = prepare(args.store, args.template)
    except (OSError, ValueError, ReviewStoreError):
        parser.exit(1, 'Cannot prepare appeal: save the matching synthetic denial in this database first.\n')
    print(result.model_dump_json(indent=2))


if __name__ == '__main__':
    main()
