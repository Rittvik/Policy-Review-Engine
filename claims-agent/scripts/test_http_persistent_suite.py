"""Tests all 18 samples in sequence via HTTP API with save=True without clearing history."""
import json
import re
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8088"

def get_token():
    req = urllib.request.Request(f"{BASE_URL}/")
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")
        match = re.search(r'<meta\s+name="review-token"\s+content="([^"]+)"', html)
        if not match:
            raise RuntimeError("Could not find meta review-token in HTML")
        return match.group(1)

def get_sample(name):
    req = urllib.request.Request(f"{BASE_URL}/api/samples/{name}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def post_review(claim_dict, token, save=True):
    payload = {
        "claim": claim_dict,
        "mode": "disabled",
        "document_ids": [],
        "save": save
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/review",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-review-token": token
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def post_appeal(appeal_dict, token):
    data = json.dumps(appeal_dict).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/appeal",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-review-token": token
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def run():
    token = get_token()
    print(f"[*] Retrieved UI session token: {token[:8]}...")
    
    # We test all 18 samples sequentially with save=True into SQLite WITHOUT clearing history between tests!
    samples_order = [
        ("covered", "approve_pre_authorization"),
        ("mri-no-pt", "route_to_senior_reviewer"),
        ("appeal-denial", "deny_claim"),
        ("appeal-submission", "approve_pre_authorization"),
        ("payment", "approve_claim_payment"),
        ("missing", "request_missing_documentation"),
        ("inactive", "deny_claim"),
        ("duplicate", "deny_claim"),
        ("coding-mismatch", "route_to_coding_review"),
        ("high-value", "route_to_senior_reviewer"),
        ("ct-emergency", "approve_claim_payment"),
        ("dme-over", "route_to_senior_reviewer"),
        ("inpatient", "approve_claim_payment"),
        ("inpatient-nonelective", "approve_claim_payment"),
        ("drug", "approve_claim_payment"),
        ("dme-500", "approve_claim_payment"),
        ("specialty", "approve_claim_payment"),
    ]

    print("\n" + "=" * 90)
    print(f"{'SAMPLE KEY':24} | {'EXPECTED ACTION':25} | {'ACTUAL ACTION':25} | {'STATUS'}")
    print("=" * 90)

    for key, exp_action in samples_order:
        sample = get_sample(key)
        if key == "appeal-submission":
            res = post_appeal(sample, token)
        else:
            res = post_review(sample, token, save=True)
        
        action = res["decision"]["action"]
        reason = res["decision"]["context"]["reason"]
        status = "PASS" if action == exp_action else "FAIL"
        
        # Verify it was not rejected as duplicate unless key is duplicate
        if key != "duplicate" and "duplicate" in reason.lower() and action == "deny_claim":
            status = "FAIL (UNINTENDED DUPLICATE)"

        print(f"{key:24} | {exp_action:25} | {action:25} | {status}")
        assert status == "PASS", f"Sample {key} failed: got {action}, expected {exp_action}. Reason: {reason}"

    print("=" * 90)
    print("[*] SUCCESS: All samples tested in sequence with save=True without clearing history!")

if __name__ == "__main__":
    run()
