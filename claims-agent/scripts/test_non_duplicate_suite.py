"""Verification script to test all 18 samples in sequence against a persistent ReviewStore without clearing history."""
import json
import tempfile
from pathlib import Path
from decimal import Decimal

from claims_agent.schemas import Claim
from claims_agent.appeals import AppealSubmission
from claims_agent.controller import ReviewController
from claims_agent.decisions import DECISION_ADAPTER
from claims_agent.reviews import ReviewStore
from claims_agent.evaluation import bind_appeal
from claims_agent.web import SAMPLES

ROOT = Path(__file__).resolve().parents[1]

def verify_all_samples_in_sequence(samples_dict=None):
    if samples_dict is None:
        samples_dict = SAMPLES

    reviewer = ReviewController(ROOT / "policies", ROOT / ".cache")
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "persistent_history.sqlite3"
        store = ReviewStore(db_path)

        results = []
        # We test in order:
        # Note: If appeal-denial runs before appeal-submission, appeal-submission should overturn the denial!
        for key, (label, rel_path) in samples_dict.items():
            file_path = ROOT / rel_path
            raw = json.loads(file_path.read_text())
            is_appeal = "request" in raw and "claim" in raw.get("request", {})

            if is_appeal:
                # Dynamic binding if prior exists in store
                prior_id = raw["request"].get("prior_review", {}).get("claim", {}).get("review_id")
                prior = store.get(prior_id) if prior_id else None
                if prior is None and raw["request"].get("prior_review"):
                    pr = raw["request"]["prior_review"]
                    try:
                        pr_claim = Claim.model_validate(pr["claim"])
                        pr_dec = DECISION_ADAPTER.validate_python(pr["decision"])
                        prior = store.save(pr_claim, pr_dec)
                    except Exception:
                        pass
                if prior is not None:
                    raw["request"]["prior_review"] = prior.model_dump(mode="json")
                    raw["request"]["claim_reference"] = prior.claim.claim_id
                    for k in ("timing_assessment", "evidence_assessment"):
                        if k in raw and isinstance(raw[k], dict) and "request" in raw[k]:
                            raw[k]["request"]["prior_review"] = prior.model_dump(mode="json")
                            raw[k]["request"]["claim_reference"] = prior.claim.claim_id
                sub = AppealSubmission.model_validate(raw)
                decision = reviewer.review_appeal(sub, store)
            else:
                claim = Claim.model_validate(raw)
                decision = reviewer.review(claim, store=store)
                # Save review to history to simulate user saving review
                store.save(claim, decision)

            results.append((key, decision.action, decision.context.reason))
            print(f"[{key:20}] => Action: {decision.action:30} Reason: {decision.context.reason[:50]}")

        return results

if __name__ == "__main__":
    verify_all_samples_in_sequence()
