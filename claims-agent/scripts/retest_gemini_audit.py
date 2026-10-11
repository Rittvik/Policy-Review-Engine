"""Retest failed/unavailable synthetic audit cases only, paced and checkpointed.
Requires explicit authorization for the external export. Never retries within a case.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audit_system import ROOT, render
from claims_agent.llm import extract_candidates
from claims_agent.gemini import GeminiAdapter
from claims_agent.schemas import Claim
from claims_agent.policy import ingest_policy,HORIZONCARE

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prior',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--interval',type=float,default=65);args=p.parse_args()
 if args.output.exists():p.error('Use a fresh output directory.')
 if args.interval<65:p.error('Minimum interval is 65 seconds.')
 args.output.mkdir(parents=True)
 prior=json.loads((args.prior/'results.json').read_text());gold=json.loads((args.prior/'extraction-gold.json').read_text())
 cases={g['id']:g for g in gold};pending=[r for r in prior['cases'] if r['kind']=='live Gemini' and r['result']!='PASS']
 if len(pending)>13:p.error('This run is capped at 13 authorized calls.')
 report=dict(timestamp=datetime.now(timezone.utc).isoformat(),cases=[],prior_run=str(args.prior),interval_seconds=args.interval)
 index=ingest_policy(HORIZONCARE,ROOT/'policies',ROOT/'.policy-cache').index
 for n,old in enumerate(pending):
  if n:time.sleep(args.interval)
  case=cases[old['id'].removeprefix('live-')];claim=Claim.model_validate_json(json.dumps(case['claim']));start=time.monotonic()
  result=extract_candidates(claim,index,document_ids=tuple(case['document_ids']),adapter=GeminiAdapter())
  grades=[]
  if result.candidates:
   for e,a in zip(case['expected'],result.candidates.findings):
    status=e['status']==a.status;anchors=all(any(r.document_id==an['document_id'] and an['quote'] in r.quote for r in a.document_refs) for an in e['anchors'])
    grades.append(dict(topic=e['topic'],status_match=status,anchor_match=anchors,score=60*status+40*(status and anchors)))
  correctness=round(sum(g['score'] for g in grades)/len(grades),1) if grades else (None if result.status=='unavailable' else 0)
  row=dict(id=old['id'],category=old['category'],kind='live Gemini',expected=case['expected'],actual=result.model_dump(mode='json'),trust=result.evidence_reliability,correctness=correctness,correctness_findings=grades,result='UNAVAILABLE' if result.status=='unavailable' else ('PASS' if correctness==100 else 'FAIL'),elapsed_seconds=round(time.monotonic()-start,2))
  report['cases'].append(row);render(report,args.output);print(row['id'],row['result'],result.reason,result.validation_error,flush=True)
if __name__=='__main__':main()
