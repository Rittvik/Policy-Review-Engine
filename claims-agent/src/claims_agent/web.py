"""Local FastAPI review desk; run from the extracted project root.

The local operator is trusted. Loopback binding and browser request protections
are not authentication and this application is not a multi-user deployment.
"""
import json
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .assessment_review import CARRY_FIELDS, apply_review, parse_packet, prepare_packet, review_template
from .cli import read_json
from .controller import ReviewController
from .decisions import DECISION_ADAPTER, InputValidationFailure
from .llm import ExtractionResult, extract_candidates, prepare_extraction
from .policy import PolicyError, ingest_policy, resolve_policy
from .reviews import ReviewStore, ReviewStoreError
from .schemas import Claim

MAX_BODY = 2 * 1024 * 1024
SAMPLES = {

    # Policy Section 5.1 & Section 4: Lumbar Spine MRI Clinical Reviews & Pre-Authorization
    'clinical': ('MRI (Lumbar) — Clinical assessment needed (Sec 4 & 5.1)', 'examples/clinical_review/source_claim.json'),
    'covered': ('MRI (Lumbar) — Pre-authorization approved (Sec 5.1)', 'examples/covered_mri.json'),
    'mri-no-pt': ('MRI (Lumbar) — Conservative therapy not attempted (Sec 5.1 denial)', 'examples/services/mri-no-pt.json'),

    # Policy Section 8: Formal Claims Appeals
    'appeal-denial': ('Appeal — Prior denial notice baseline (Sec 8 DENIAL-1)', 'examples/appeal_original_denial.json'),
    'appeal-submission': ('Appeal — Reassessment with new clinical evidence (Sec 8 overturn)', 'examples/appeal_submission.json'),

    # Core Post-Service Payment Workflow
    'payment': ('Claim Payment — Covered payment approval ($900.00)', 'examples/covered_payment.json'),

    # Policy Section 3.2: Documentation Prerequisites
    'missing': ('Documentation — Missing clinical notes (Sec 3.2 pended)', 'examples/missing_document.json'),

    # Policy Section 2: Member Eligibility & Plan Status
    'inactive': ('Eligibility — Inactive plan membership (Sec 2 denial)', 'examples/inactive_membership.json'),

    # Policy Section 7.1: Duplicate Claim Processing Rule
    'duplicate': ('Claims Rule — Duplicate claim submission (Sec 7.1 denial)', 'examples/duplicate_claim.json'),

    # Policy Section 7.2: Coding Consistency
    'coding-mismatch': ('Claims Rule — Coding inconsistency review (Sec 7.2)', 'examples/coding_mismatch.json'),

    # Task Rule: High-Dollar Audit Threshold
    'high-value': ('Governance — High-value claim audit (> $5,000 threshold)', 'examples/high_value.json'),

    # Policy Section 3.1: Explicit Prior Authorization Categories
    'ct-emergency': ('CT Scan — Emergency exception without PA (Sec 3.1 waiver)', 'examples/services/ct-emergency.json'),
    'dme-over': ('DME Equipment — Cost > $500 without PA (Sec 3.1 requirement)', 'examples/services/dme-over-500-no-auth.json'),
    'inpatient': ('Inpatient Hospital — Elective admission with PA (Sec 3.1)', 'examples/services/inpatient-elective.json'),
    'inpatient-nonelective': ('Inpatient Hospital — Non-elective admission (Sec 3.1)', 'examples/services/inpatient-nonelective.json'),
    'drug': ('Prescription Drug — Formulary covered (Sec 1)', 'examples/services/drug-formulary.json'),
    'dme-500': ('DME Equipment — Cost exactly $500 without PA (Sec 3.1)', 'examples/services/dme-exactly-500.json'),
    'specialty': ('Specialty Drug — Formulary PA required & approved (Sec 3.1)', 'examples/services/specialty-pa-required.json'),
}


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claim: dict | Claim
    mode: Literal['auto', 'disabled', 'gemini', 'recorded'] = 'auto'
    document_ids: tuple[str, ...] = ()
    save: bool = False


def create_app(root: Path | None = None, store_path: Path | None = None):
    import os
    root = Path(root or Path.cwd()).resolve()
    assets = Path(__file__).resolve().parent
    for candidate_env in (root / ".env", root / "src" / "claims_agent" / ".env", assets / ".env"):
        if candidate_env.exists():
            for line in candidate_env.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v
    app = FastAPI(title='Claims review desk', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])
    app.mount('/static', StaticFiles(directory=assets/'static'), name='static')
    templates = Jinja2Templates(directory=assets/'templates')
    token = secrets.token_urlsafe(32)
    reviewer = ReviewController(root/'policies', root/'.policy-cache')
    db_path = store_path or root/'.review-history/web.sqlite3'

    @app.middleware('http')
    async def browser_boundary(request, call_next):
        if request.method not in {'GET', 'HEAD'} and not secrets.compare_digest(
                request.headers.get('x-review-token', ''), token):
            return JSONResponse({'error': 'Reload the page before submitting.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @app.exception_handler(ValidationError)
    async def invalid_model(request, exc):
        fields = ', '.join('.'.join(str(v) for v in item['loc']) or 'assessment' for item in exc.errors())
        return JSONResponse({'error': 'Invalid or incomplete fields: '+fields}, status_code=422)

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse({'error': f'Input could not be verified: {exc}. Check source quotations, packet, review ID and completed findings.'}, status_code=422)

    @app.exception_handler(PolicyError)
    async def policy_error(request, exc):
        return JSONResponse({'error': 'Matching policy evidence is unavailable.'}, status_code=503)

    @app.exception_handler(ReviewStoreError)
    async def store_error(request, exc):
        return JSONResponse({'error': 'Review could not be saved. Use a new review ID and check the local store. No successful save is implied.'}, status_code=409)

    @app.exception_handler(OSError)
    async def file_error(request, exc):
        return JSONResponse({'error': 'Local data is unavailable. Start the server from the project root and check file access.'}, status_code=503)

    async def body(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'Send JSON input.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise HTTPException(413, 'Input exceeds the 2 MiB limit.')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate field')
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError('Nonfinite number')
        data = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
        if not isinstance(data, dict):
            raise ValueError('Expected object')
        return data

    def index_for(claim):
        return ingest_policy(resolve_policy(claim.insurer, claim.plan_name), reviewer.policy_dir, reviewer.cache_dir).index

    @app.get('/')
    def home(request: Request):
        return templates.TemplateResponse(request=request, name='index.html', context={
            'token': token, 'samples': [(key, value[0]) for key, value in SAMPLES.items()]})

    @app.get('/api/samples/{name}')
    def sample(name: str):
        if name not in SAMPLES:
            raise HTTPException(404, 'Sample not found.')
        return read_json(root/SAMPLES[name][1])

    def run_review(data):
        import os
        inputs = ReviewInput.model_validate(data)
        raw_claim = inputs.claim
        store = ReviewStore(db_path)

        if isinstance(raw_claim, Claim):
            claim = raw_claim
            is_appeal_submission = False
        elif (isinstance(raw_claim, dict) and "request" in raw_claim
              and isinstance(raw_claim.get("request"), dict) and "claim" in raw_claim["request"]):
            is_appeal_submission = True
            claim = Claim.model_validate(raw_claim["request"]["claim"])
            raw_claim["request"]["claim"] = claim.model_dump(mode="json")
        else:
            claim = Claim.model_validate(raw_claim)
            is_appeal_submission = False

        if is_appeal_submission:
            if not isinstance(raw_claim, dict):
                raise ValueError("Invalid appeal submission")
            if "request" in raw_claim and isinstance(raw_claim["request"], dict):
                prior_id = raw_claim["request"].get("prior_review", {}).get("claim", {}).get("review_id")
                prior = store.get(prior_id) if prior_id else None
                if prior is None:
                    c_sub = raw_claim["request"].get("claim", {})
                    candidates = [r for r in store.history(insurer=c_sub.get("insurer"), plan_name=c_sub.get("plan_name"), member_id=c_sub.get("member_id"))
                                  if r.decision.action == "deny_claim" and r.claim.claim_id == c_sub.get("claim_id")]
                    if candidates:
                        prior = candidates[0]
                if prior is not None:
                    raw_claim["request"]["prior_review"] = prior.model_dump(mode="json")
                    raw_claim["request"]["claim_reference"] = prior.claim.claim_id
                    for k in ("timing_assessment", "evidence_assessment"):
                        if k in raw_claim and isinstance(raw_claim[k], dict) and "request" in raw_claim[k]:
                            raw_claim[k]["request"]["prior_review"] = prior.model_dump(mode="json")
                            raw_claim[k]["request"]["claim_reference"] = prior.claim.claim_id
            decision = reviewer.review_appeal(raw_claim, store)
            if isinstance(decision, InputValidationFailure):
                raise ValueError("Invalid appeal submission")
            saved = any(t.rule_id == "review_persistence" and t.outcome == "satisfied"
                        for t in decision.context.decision_trace)
            result = dict(decision=decision.model_dump(mode='json'), extraction=None,
                          packet=None, template=None, carry_forward=[], saved=saved)
        else:
            decision = reviewer.review(claim, store=store)
            if isinstance(decision, InputValidationFailure):
                raise ValueError('Invalid claim')
            result = dict(decision=decision.model_dump(mode='json'), extraction=None,
                          packet=None, template=None, carry_forward=[], saved=False)

        should_extract = False
        if not is_appeal_submission:
            policy_unresolved = any(t.rule_id == 'policy_resolution' and t.outcome != 'satisfied'
                                    for t in decision.context.decision_trace)
            if not policy_unresolved:
                if inputs.mode in {'gemini', 'recorded'}:
                    should_extract = True
                elif inputs.mode == 'auto':
                    admin_blocked = decision.action in {'deny_claim', 'request_missing_documentation', 'approve_pre_authorization', 'approve_claim_payment'} or any(
                        t.rule_id in {'inactive_plan', 'member_eligibility', 'duplicate_claim'} and t.outcome in {'failed', 'matched'}
                        for t in decision.context.decision_trace
                    )
                    has_docs = bool(inputs.document_ids or (claim.documents and any(
                        d.status == 'provided' and d.document_type in {'clinical_note', 'prior_treatment_history', 'formulary'}
                        for d in claim.documents
                    )))
                    needs_clinical = claim.clinical_assessment is None
                    is_clinical_route = decision.action == 'route_to_senior_reviewer'
                    if not admin_blocked and is_clinical_route and has_docs and needs_clinical:
                        should_extract = True

        if should_extract:
            doc_ids = inputs.document_ids
            if not doc_ids and claim.documents:
                doc_ids = tuple(d.document_id for d in claim.documents if d.status == 'provided' and d.document_type in {'clinical_note', 'prior_treatment_history', 'formulary'})
            if not doc_ids or len(set(doc_ids)) != len(doc_ids):
                raise ValueError('Choose unique documents')
            index = None
            try:
                index = index_for(claim)
            except PolicyError:
                should_extract = False
            if should_extract and index is not None:
                extraction_origin = 'live_adapter'
                if inputs.mode == 'recorded':
                    extraction_origin = 'recorded'
                    prepared = prepare_extraction(claim, index, document_ids=doc_ids)
                    extraction = None
                    for path in ('examples/clinical_review/extraction.json', 'examples/services/ct-extraction.json'):
                        if not (root/path).exists():
                            continue
                        candidate = ExtractionResult.model_validate_json(json.dumps(read_json(root/path)['advisory']))
                        if candidate.input_sha256 == prepared.input_sha256:
                            extraction = candidate
                            break
                    if extraction is None:
                        raise ValueError('Recorded response belongs to another source')
                else:
                    from .gemini import GeminiAdapter
                    has_key = bool(os.environ.get("GEMINI_API_KEY"))
                    if not has_key and inputs.mode == 'auto':
                        # In auto mode offline, check if recorded benchmark fixture matches for seamless demonstration
                        prepared = prepare_extraction(claim, index, document_ids=doc_ids)
                        extraction = None
                        for path in ('examples/clinical_review/extraction.json', 'examples/services/ct-extraction.json'):
                            if (root/path).exists():
                                candidate = ExtractionResult.model_validate_json(json.dumps(read_json(root/path)['advisory']))
                                if candidate.input_sha256 == prepared.input_sha256:
                                    extraction_origin = 'recorded'
                                    extraction = candidate
                                    break
                        if extraction is None:
                            extraction = extract_candidates(claim, index, document_ids=doc_ids, adapter=GeminiAdapter())
                    else:
                        extraction = extract_candidates(claim, index, document_ids=doc_ids, adapter=GeminiAdapter())
                from .trust import evidence_reliability
                prepared = prepare_extraction(claim, index, document_ids=doc_ids)
                runtime_score = evidence_reliability(extraction, prepared, origin=extraction_origin)
                result['extraction'] = extraction.model_dump(mode='json')
                result['extraction']['evidence_reliability'] = runtime_score
                if extraction.status == 'validated_candidates' and claim.clinical_assessment is None:
                    packet = prepare_packet(claim, extraction, doc_ids, index, reviewer)
                    result.update(packet=packet.model_dump(mode='json'), template=review_template(packet),
                                  carry_forward=[name for name in CARRY_FIELDS if getattr(claim, name) is not None])
        if inputs.save and not is_appeal_submission:
            ReviewStore(db_path).save(claim, decision)
            result['saved'] = True

        # Attach AI Intelligence insights (Fast-Track, Adverse Determination Notice, Appeal Synthesis)
        try:
            from .intelligence import evaluate_fast_track, generate_adverse_notice, synthesize_appeal
            eval_target = claim
            ft = evaluate_fast_track(eval_target, decision)
            notice = generate_adverse_notice(eval_target, decision)
            appeal_synth = None
            if is_appeal_submission and isinstance(raw_claim, dict):
                req = raw_claim.get("request", {})
                prior_data = req.get("prior_review") if isinstance(req, dict) else None
                if prior_data and isinstance(prior_data, dict):
                    orig_claim = prior_data.get("claim", {})
                    orig_dec = prior_data.get("decision", {})
                    appeal_synth = synthesize_appeal(orig_claim, orig_dec, raw_claim).model_dump(mode="json")
            result['intelligence'] = {
                "fast_track": ft.model_dump(mode="json"),
                "adverse_notice": notice.model_dump(mode="json") if notice else None,
                "appeal_synthesis": appeal_synth,
            }
        except Exception:
            result['intelligence'] = None

        return result

    @app.post('/api/review')
    async def review(request: Request):
        return await run_in_threadpool(run_review, await body(request))

    @app.post('/api/preview')
    async def preview(request: Request):
        data = ReviewInput.model_validate(await body(request))
        raw_claim = data.claim
        if isinstance(raw_claim, dict) and 'request' in raw_claim and isinstance(raw_claim.get('request'), dict) and 'claim' in raw_claim['request']:
            claim_obj = Claim.model_validate(raw_claim['request']['claim'])
        elif isinstance(raw_claim, Claim):
            claim_obj = raw_claim
        else:
            claim_obj = Claim.model_validate(raw_claim)

        def prepare():
            doc_ids = data.document_ids
            if not doc_ids and claim_obj.documents:
                doc_ids = tuple(d.document_id for d in claim_obj.documents if d.status == 'provided' and d.document_type in {'clinical_note', 'prior_treatment_history', 'formulary'})
            if not doc_ids:
                raise ValueError('No clinical documents available for preview.')
            prepared = prepare_extraction(claim_obj, index_for(claim_obj), document_ids=doc_ids)
            return {'payload': prepared.payload.model_dump(mode='json'), 'input_sha256': prepared.input_sha256}
        return await run_in_threadpool(prepare)

    @app.post('/api/confirm')
    async def confirm(request: Request):
        data = await body(request)
        if set(data) != {'packet', 'assessment'}:
            raise ValueError('Expected packet and assessment')
        def apply():
            packet = parse_packet(data['packet'])
            saved = apply_review(packet, data['assessment'], index_for(packet.source_claim), reviewer, ReviewStore(db_path))
            from .trust import evidence_reliability
            prepared = prepare_extraction(packet.source_claim, index_for(packet.source_claim), document_ids=packet.document_ids)
            return {'decision': saved.decision.model_dump(mode='json'), 'saved': True,
                    'evidence_reliability': evidence_reliability(packet.extraction, prepared, origin='recorded'),
                    'review_id': saved.claim.review_id, 'previous_review_id': saved.previous_review_id}
        return await run_in_threadpool(apply)

    @app.post('/api/appeal')
    async def appeal(request: Request):
        data = await body(request)
        def submit():
            store = ReviewStore(db_path)
            if isinstance(data, dict) and "request" in data and isinstance(data["request"], dict):
                prior_id = data["request"].get("prior_review", {}).get("claim", {}).get("review_id")
                prior = store.get(prior_id) if prior_id else None
                if prior is None:
                    c_sub = data["request"].get("claim", {})
                    candidates = [r for r in store.history(insurer=c_sub.get("insurer"), plan_name=c_sub.get("plan_name"), member_id=c_sub.get("member_id"))
                                  if r.decision.action == "deny_claim" and r.claim.claim_id == c_sub.get("claim_id")]
                    if candidates:
                        prior = candidates[0]
                if prior is not None:
                    data["request"]["prior_review"] = prior.model_dump(mode="json")
                    data["request"]["claim_reference"] = prior.claim.claim_id
                    for k in ("timing_assessment", "evidence_assessment"):
                        if k in data and isinstance(data[k], dict) and "request" in data[k]:
                            data[k]["request"]["prior_review"] = prior.model_dump(mode="json")
                            data[k]["request"]["claim_reference"] = prior.claim.claim_id
            decision = reviewer.review_appeal(data, store)
            if isinstance(decision, InputValidationFailure):
                raise ValueError('Invalid appeal submission')
            saved = any(t.rule_id == 'review_persistence' and t.outcome == 'satisfied'
                        for t in decision.context.decision_trace)
            return {'decision': decision.model_dump(mode='json'), 'saved': saved,
                    'review_id': decision.context.review_id}
        return await run_in_threadpool(submit)

    @app.get('/api/history')
    def recent_history(page: int = 1, limit: int = 5):
        if page < 1:
            page = 1
        if limit < 1:
            limit = 5
        store = ReviewStore(db_path)
        total = store.count()
        offset = (page - 1) * limit
        records = store.recent(limit=limit, offset=offset)
        total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1
        return {
            'records': [r.model_dump(mode='json') for r in records],
            'total': total,
            'page': page,
            'limit': limit,
            'total_pages': total_pages,
        }


    @app.get('/api/history/{review_id}')
    def history(review_id: str):
        store = ReviewStore(db_path)
        record = store.get(review_id)
        if record is None:
            raise HTTPException(404, f"No saved review has ID '{review_id}'.")
        claim = record.claim
        records = store.history(insurer=claim.insurer, plan_name=claim.plan_name,
                                member_id=claim.member_id, claim_id=claim.claim_id)
        return {
            'target_review_id': review_id,
            'record': record.model_dump(mode='json'),
            'records': [r.model_dump(mode='json') for r in records],
        }

    @app.delete('/api/history')
    @app.post('/api/history/clear')
    def clear_history():
        store = ReviewStore(db_path)
        deleted = store.clear()
        return {'status': 'cleared', 'deleted_count': deleted}

    @app.get('/api/evaluation')
    def get_evaluation():
        results_file = root / 'evaluation' / 'results.json'
        rubric_file = root / 'evaluation' / 'rubric.md'
        rubric_text = rubric_file.read_text() if rubric_file.exists() else ''
        phoenix_file = root / 'evaluation' / 'phoenix_results.json'
        phoenix_data = json.loads(phoenix_file.read_text()) if phoenix_file.exists() else None
        if results_file.exists():
            data = json.loads(results_file.read_text())
            data['rubric'] = rubric_text
            if phoenix_data:
                data['phoenix'] = phoenix_data
            return data
        from .evaluation import run_evaluation, write_report
        cases_dir = root / 'evaluation'
        report = run_evaluation(cases_dir, root / 'policies', root / '.policy-cache', 'offline')
        write_report(report, root / 'evaluation')
        report['rubric'] = rubric_text
        if phoenix_data:
            report['phoenix'] = phoenix_data
        return report

    @app.post('/api/evaluation/run')
    async def run_evals():
        from .evaluation import run_evaluation, write_report
        cases_dir = root / 'evaluation'
        def execute():
            report = run_evaluation(cases_dir, root / 'policies', root / '.policy-cache', 'offline')
            write_report(report, root / 'evaluation')
            rubric_file = root / 'evaluation' / 'rubric.md'
            report['rubric'] = rubric_file.read_text() if rubric_file.exists() else ''
            phoenix_file = root / 'evaluation' / 'phoenix_results.json'
            if phoenix_file.exists():
                report['phoenix'] = json.loads(phoenix_file.read_text())
            return report
        return await run_in_threadpool(execute)
    @app.post('/api/intelligence/fast-track')
    async def api_fast_track(request: Request):
        payload = await body(request)
        from .intelligence import evaluate_fast_track
        claim_data = payload.get("claim", payload) if isinstance(payload, dict) else payload
        decision_data = payload.get("decision") if isinstance(payload, dict) else None
        return evaluate_fast_track(claim_data, decision_data).model_dump(mode="json")

    @app.post('/api/intelligence/adverse-notice')
    async def api_adverse_notice(request: Request):
        payload = await body(request)
        from .intelligence import generate_adverse_notice
        claim_data = payload.get("claim", payload) if isinstance(payload, dict) else payload
        decision_data = payload.get("decision") if isinstance(payload, dict) else None
        notice = generate_adverse_notice(claim_data, decision_data)
        if notice is None:
            return {"notice": None, "adverse": False, "message": "Claim is approved; no adverse notice required."}
        return notice.model_dump(mode="json")

    @app.post('/api/intelligence/appeal-synthesis')
    async def api_appeal_synthesis(request: Request):
        payload = await body(request)
        from .intelligence import synthesize_appeal
        orig_claim = payload.get("original_claim", {})
        orig_dec = payload.get("original_decision", {})
        appeal_sub = payload.get("appeal_submission", payload)
        return synthesize_appeal(orig_claim, orig_dec, appeal_sub).model_dump(mode="json")

    return app


app = create_app()
