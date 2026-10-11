"""Local review commands with opt-in extraction and explicit reviewer confirmation."""

import argparse
import json
from pathlib import Path

from .controller import ReviewController
from .decisions import InputValidationFailure
from .llm import CandidateResponse, INSTRUCTION_PROMPT, MockAdapter, ModelCall, extract_candidates, prepare_extraction
from .policy import HORIZONCARE, PolicyError, ingest_policy, resolve_policy
from .reviews import ReviewStore, ReviewStoreError
from .schemas import Claim


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("nonfinite_json_number")

    data = json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(data, dict):
        raise ValueError("expected_json_object")
    return data


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("ingest-policies", "review", "appeal", "evaluate", "prepare-assessment", "review-assessment", "evaluate-services"):
        command = commands.add_parser(name)
        command.add_argument("--policy-dir", type=Path, default=Path("policies"))
        command.add_argument("--cache-dir", type=Path, default=Path(".policy-cache"))
        command.add_argument("--format", choices=("json", "human"), default="json")
        if name == "prepare-assessment":
            command.add_argument("--input", required=True, type=Path)
            command.add_argument("--extraction", required=True, type=Path)
            command.add_argument("--document", action="append", required=True)
            command.add_argument("--packet-output", required=True, type=Path)
            command.add_argument("--review-output", required=True, type=Path)
            continue
        if name == "review-assessment":
            command.add_argument("--packet", required=True, type=Path)
            command.add_argument("--assessment", required=True, type=Path)
            command.add_argument("--store", type=Path, default=Path(".review-history/reviews.sqlite3"))
            continue
        if name == "evaluate-services":
            command.add_argument("--samples-dir", type=Path, default=Path("examples/services"))
            command.add_argument("--output-dir", type=Path, default=Path("evaluation"))
            continue
        if name == "evaluate":
            command.add_argument("--cases-dir", type=Path, default=Path("evaluation"))
            command.add_argument("--output-dir", type=Path, default=Path("evaluation"))
            command.add_argument("--mode", choices=("offline", "gemini"), default="offline")
            command.add_argument("--preview-llm-input", action="store_true")
            continue
        if name == "ingest-policies":
            continue
        command.add_argument("--input", required=True, type=Path)
        command.add_argument("--store", type=Path, default=Path(".review-history/reviews.sqlite3"))
        if name == "review":
            command.add_argument("--save", action="store_true")
            command.add_argument("--llm", choices=("disabled", "mock", "gemini"), default="disabled")
            command.add_argument("--llm-fixture", type=Path)
            command.add_argument("--document", action="append", default=[])
            command.add_argument("--preview-llm-input", action="store_true")
    return result


def emit(data, display):
    if display == "json" or "decision" not in data:
        print(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))
        return
    decision = data["decision"]
    if decision.get("kind") == "validation_error":
        print("Input validation failed:")
        for issue in decision["issues"]:
            print(f"  {issue}")
    else:
        context = decision["context"]
        print(f"Action: {decision['action']} (stub)")
        print(f"Reason: {context['reason']}")
        print("Arguments: " + json.dumps(decision["arguments"]))
        for label, key in (("Missing", "missing_information"), ("Unresolved", "unresolved_information")):
            print(f"{label}: " + (", ".join(context[key]) or "none"))
        print("Policy citations:")
        for ref in context["policy_evidence"]:
            print(f"  Section {ref['section']}, page {ref['source_page']}: {ref['quote']}")
        print("Rule trace:")
        for entry in context["decision_trace"]:
            print(f"  {entry['rule_id']}: {entry['outcome']} — {entry['reason']}")
    print("Persistence: " + json.dumps(data["persistence"]))
    if data.get("assessment_review"):
        print("Reviewer-confirmed clinical assessment: " + json.dumps(data["assessment_review"]))
    if data["advisory"] is not None:
        if data.get("assessment_review"):
            print("Original Gemini/mock candidates — explicitly reviewed before use:")
        else:
            print("Advisory extraction — untrusted findings; did not affect the decision:")
        print(json.dumps(data["advisory"], indent=2, ensure_ascii=False))


def execute(args):
    if args.command == "evaluate-services":
        from .service_evaluation import run_service_evaluation
        result = run_service_evaluation(args.samples_dir, args.policy_dir, args.cache_dir, args.output_dir)
        return result, 0 if result['passed'] else 1
    if args.command in {"prepare-assessment", "review-assessment"}:
        from .assessment_review import parse_packet, prepare_packet, review_template, apply_review
        reviewer = ReviewController(args.policy_dir, args.cache_dir)
        if args.command == "prepare-assessment":
            # Refuse overwrites, including accidentally targeting the source input.
            if args.packet_output.resolve() == args.review_output.resolve() or any(
                p.exists() for p in (args.packet_output, args.review_output)
            ):
                raise ValueError("Assessment output files must be new and distinct")
            if not all(p.parent.is_dir() for p in (args.packet_output, args.review_output)):
                raise ValueError("Create assessment output directories first")
            claim = Claim.model_validate(read_json(args.input))
            extraction = read_json(args.extraction)
            if "advisory" in extraction:
                extraction = extraction["advisory"]
            index = ingest_policy(resolve_policy(claim.insurer, claim.plan_name), args.policy_dir, args.cache_dir).index
            packet = prepare_packet(claim, extraction, tuple(args.document), index, reviewer)
            template = review_template(packet)
            # Exclusive creation ensures existing reviews are never overwritten.
            with args.packet_output.open("x", encoding="utf-8") as output:
                output.write(packet.model_dump_json(indent=2) + "\n")
            with args.review_output.open("x", encoding="utf-8") as output:
                output.write(json.dumps(template, indent=2, ensure_ascii=False) + "\n")
            return {"cli_schema_version": 1, "packet_sha256": packet.packet_sha256,
                    "packet": str(args.packet_output), "review_template": str(args.review_output),
                    "available_carry_forward_assessments": [name for name in (
                        "coding_assessment", "treatment_history_applicability", "exclusion_assessment",
                        "payment_determination", "authorization_assessment", "equipment_cost_assessment") if getattr(claim, name) is not None],
                    "status": "awaiting_reviewer_assessment"}, 0
        packet = parse_packet(read_json(args.packet))
        assessment = read_json(args.assessment)
        claim = packet.source_claim
        index = ingest_policy(resolve_policy(claim.insurer, claim.plan_name), args.policy_dir, args.cache_dir).index
        saved = apply_review(packet, assessment, index, reviewer, ReviewStore(args.store))
        from .trust import evidence_reliability
        scored_advisory = packet.extraction.model_dump(mode="json")
        scored_advisory['evidence_reliability'] = evidence_reliability(
            packet.extraction, prepare_extraction(claim, index, document_ids=packet.document_ids), origin='recorded')
        return {"cli_schema_version": 1, "decision": saved.decision.model_dump(mode="json"),
                "advisory": scored_advisory,
                "persistence": {"status": "saved", "review_id": saved.claim.review_id},
                "assessment_review": {"reviewer_id": assessment["reviewer_id"],
                    "source_review_id": packet.source_claim.review_id,
                    "packet_sha256": packet.packet_sha256,
                    "clinical_assessment": saved.claim.clinical_assessment.model_dump(mode="json")}}, 0
    if args.command == "evaluate":
        from .evaluation import preview_calls, run_evaluation, write_report
        if args.preview_llm_input:
            return preview_calls(args.cases_dir, args.policy_dir, args.cache_dir, args.output_dir), 0
        report = run_evaluation(args.cases_dir, args.policy_dir, args.cache_dir, args.mode)
        path = write_report(report, args.output_dir)
        return {"cli_schema_version": 1, "mode": args.mode, "passed": report["passed"],
                "live_status": report["live_status"], "metrics": report["metrics"], "report": path}, 0 if report["passed"] else 1
    if args.command == "ingest-policies":
        result = ingest_policy(HORIZONCARE, args.policy_dir, args.cache_dir)
        return {"cli_schema_version": 1, "policy_id": result.index.policy_id,
                "source_sha256": result.index.source_sha256,
                "chunk_count": len(result.index.chunks), "cache_hit": result.cache_hit}, 0

    payload = read_json(args.input)
    reviewer = ReviewController(args.policy_dir, args.cache_dir)
    advisory = None
    persistence = {"status": "not_requested"}
    code = 0
    if args.command == "appeal":
        decision = reviewer.review_appeal(payload, ReviewStore(args.store))
        if not isinstance(decision, InputValidationFailure):
            saved = any(t.rule_id == "review_persistence" and t.outcome == "satisfied"
                        for t in decision.context.decision_trace)
            persistence = {"status": "saved" if saved else "failed",
                           "review_id": decision.context.review_id}
            if not saved:
                persistence["error"] = "appeal_not_saved"
                code = 1
    else:
        decision = reviewer.review(payload)
        if not isinstance(decision, InputValidationFailure):
            claim = Claim.model_validate(payload)
            if args.llm != "disabled":
                try:
                    spec = resolve_policy(claim.insurer, claim.plan_name)
                    index = ingest_policy(spec, args.policy_dir, args.cache_dir).index
                except PolicyError:
                    index = None
                selection = {"document_ids": tuple(args.document)}
                if args.preview_llm_input:
                    prepared = prepare_extraction(claim, index, **selection)
                    call = ModelCall(instruction=INSTRUCTION_PROMPT,
                        payload_json=prepared.payload.model_dump_json(),
                        response_schema_json=json.dumps(CandidateResponse.model_json_schema()))
                    return {"cli_schema_version": 1, "preview_only": True,
                            "model_call": call.model_dump()}, 0
                if args.llm == "mock":
                    fixture = read_json(args.llm_fixture)
                    identity = fixture.get("request_id")
                    if not isinstance(identity, str):
                        raise ValueError("invalid_fixture_identity")
                    adapter = MockAdapter({identity: json.dumps(fixture)})
                else:
                    from .gemini import GeminiAdapter
                    adapter = GeminiAdapter()
                advisory = extract_candidates(claim, index, adapter=adapter, **selection).model_dump(mode="json")
            if args.save:
                try:
                    saved = ReviewStore(args.store).save(claim, decision)
                    persistence = {"status": "saved", "review_id": saved.claim.review_id}
                except (ReviewStoreError, OSError):
                    persistence = {"status": "failed", "error": "review_not_saved"}
                    code = 1
    if isinstance(decision, InputValidationFailure):
        code = 2
    return {"cli_schema_version": 1, "decision": decision.model_dump(mode="json"),
            "advisory": advisory, "persistence": persistence}, code


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.command == "review":
        if args.llm == "disabled" and (args.document or args.llm_fixture or args.preview_llm_input):
            cli.error("Extraction options require --llm mock or --llm gemini")
        if args.llm != "disabled" and (not args.document or len(args.document) != len(set(args.document))):
            cli.error("Extraction requires unique --document selections")
        if args.llm == "mock" and not args.llm_fixture and not args.preview_llm_input:
            cli.error("--llm mock requires --llm-fixture")
        if args.llm == "gemini" and args.llm_fixture:
            cli.error("--llm-fixture is only supported with --llm mock")
        if args.preview_llm_input and args.save:
            cli.error("Preview cannot be combined with --save")
    try:
        output, code = execute(args)
    except (OSError, UnicodeError, ValueError) as exc:
        operational = isinstance(exc, PolicyError)
        output = {"cli_schema_version": 1, "error": "policy_unavailable" if operational else "invalid_or_unreadable_input"}
        code = 1 if operational else 2
    except ReviewStoreError:
        output, code = {"cli_schema_version": 1, "error": "review_store_unavailable"}, 1
    emit(output, args.format)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
