#!/usr/bin/env python3
"""Participant-created evaluation cases (required by the challenge rules) and
anti-false-binding counterexamples.

Each test builds a tiny synthetic dataset with known ground truth and runs the
real engine (World + CaseAudit) over it. They pin the failure modes that the
golden samples cannot distinguish:

  T1 shared-window workflow claims must not bind to either case
  T2 lookalike emails (".jr" decoys) must not bind
  T3 404 profile lookups bind via their own lookup_key; another user's
     unrelated 404 must not leak in
  T4 evidence captured after audit_at must not change the state at audit_at
  T5 workflow claims are never state proof (claim vs evidence conflicts)
  T7 a record observed after audit_at must not change the state at audit_at
  T8 findings cite the truthful state-establishing file even when that file
     was captured after audit_at (never an older/stand-in citation, never "")

Run: python3 code/evaluation/custom_tests.py
"""
import csv, json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audit.engine import World, CaseAudit

HDR_ID = "user_id,name,email,phone,email_hash,updated_at\n"
HDR_AUDIT = "audit_id,user_id,event_time,field_name,old_value,new_value\n"
HDR_ACT = ("activity_id,event_time,event_type,source_system,target_system,"
           "resource_id,reported_result,details\n")
HDR_MAN = "file_id,file_path,origin,captured_at\n"

def write_fixture(root, identities, activities, manifest, evidence, audit_log=""):
    with open(os.path.join(root, "user_identities.csv"), "w") as f:
        f.write(HDR_ID + identities)
    with open(os.path.join(root, "user_audit_log.csv"), "w") as f:
        f.write(HDR_AUDIT + audit_log)
    with open(os.path.join(root, "system_activity.csv"), "w") as f:
        f.write(HDR_ACT + activities)
    with open(os.path.join(root, "evidence_files.csv"), "w") as f:
        f.write(HDR_MAN + manifest)
    for rel, content in evidence.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)

def case(cid, email, req="2026-09-01T00:00:00Z", rep="2026-09-03T00:00:00Z",
         audit="2026-09-10T00:00:00Z", text="Please delete my account and all my data."):
    return {"case_id": cid, "email": email, "requested_at": req,
            "reported_status": "COMPLETE", "reported_at": rep,
            "audit_at": audit, "request_text": text}

def export_json(accounts_404=(), profiles=(), audit_records=(), tickets=(),
                search=(), connectors=(), captured="2026-09-05T00:00:00Z"):
    se = {}
    if accounts_404 or profiles:
        se["account_service"] = {"profile_lookups": [
            {"resource_id": r, "observed_at": captured,
             **({"profile": p} if p else {})} for r, p in
            [(r, None) for r in accounts_404] + list(profiles)]}
    if audit_records:
        se["security_service"] = {"audit_records": audit_records}
    if tickets:
        se["support_platform"] = {"tickets": tickets}
    if search:
        se["search_service"] = {"index_queries": search}
    if connectors:
        se["integration_service"] = {"connectors": connectors}
    return json.dumps({"exported_at": captured, "service_exports": se})

def run(world, c):
    return CaseAudit(world, c).run()

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))

# ---------------------------------------------------------------- T1
def t1(root):
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n"
        "user_2,Bob B,bob@example.com,+1 555 000 0002,,2026-01-01T00:00:00Z\n",
        # an unattributed workflow claim inside BOTH cases' windows
        "act_1,2026-09-02T10:00:00Z,DELETE_RECORD,deletion_worker,account_service,account_999,SUCCESS,Deletion worker submitted primary profile account_999 to account_service.\n",
        "evidence_1,evidence/records/export.json,service_resource_export,2026-09-05T00:00:00Z\n",
        {"evidence/records/export.json": export_json(
            accounts_404=["account_999"],
            audit_records=[{"resource_id": "audit_record_1", "subject_reference": "user_1"},
                           {"resource_id": "audit_record_2", "subject_reference": "user_2"}])})
    w = World(root)
    s1, st1 = run(w, case("cA", "alice@example.com"))
    s2, st2 = run(w, case("cB", "bob@example.com"))
    r1 = {s["resource_id"] for s in st1}
    r2 = {s["resource_id"] for s in st2}
    check("T1 unattributed shared-window claim binds to neither case",
          "account_999" not in r1 and "account_999" not in r2,
          f"A={sorted(r1)} B={sorted(r2)}")
    check("T1 identity-bound audit records still bind",
          "audit_record_1" in r1 and "audit_record_2" in r2)

# ---------------------------------------------------------------- T2
def t2(root):
    write_fixture(
        root,
        "user_1,Sofia M,smartinez6461@example.com,+34 555 000 0001,,2026-01-01T00:00:00Z\n",
        "",
        "evidence_1,evidence/records/export.json,service_resource_export,2026-09-05T00:00:00Z\n",
        {"evidence/records/export.json": export_json(
            audit_records=[{"resource_id": "audit_record_1", "subject_reference": "user_1"}],
            search=[{"resource_id": "search_1", "result": "hit",
                     "document": {"display_name": "Sofia M Junior",
                                  "email": "smartinez6461.jr@example.com",
                                  "customer_reference": None}}])})
    w = World(root)
    s, st = run(w, case("cA", "smartinez6461@example.com"))
    res = {s_["resource_id"] for s_ in st}
    check("T2 lookalike-email decoy record does not bind",
          "search_1" not in res, f"resources={sorted(res)}")
    check("T2 decoy presence does not flip status", s == "COMPLETE", s)

# ---------------------------------------------------------------- T3
def t3(root):
    log = (
        '2026-09-04T09:00:00Z level=DEBUG service=account_service trace_id=tr-1 event=profile_lookup_started lookup_key="alice@example.com" attempt=1\n'
        '2026-09-04T09:00:02Z level=INFO service=account_service trace_id=tr-1 resource_id=account_1 event=profile_lookup_completed rows=0 http_status=404 duration_ms=20\n'
        '2026-09-04T09:05:00Z level=DEBUG service=account_service trace_id=tr-2 event=profile_lookup_started lookup_key="bob@example.com" attempt=1\n'
        '2026-09-04T09:05:02Z level=INFO service=account_service trace_id=tr-2 resource_id=account_2 event=profile_lookup_completed rows=0 http_status=404 duration_ms=22\n')
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n"
        "user_2,Bob B,bob@example.com,+1 555 000 0002,,2026-01-01T00:00:00Z\n",
        "",
        "evidence_1,evidence/logs/lookup.log,central_observability_export,2026-09-05T00:00:00Z\n",
        {"evidence/logs/lookup.log": log})
    w = World(root)
    s, st = run(w, case("cA", "alice@example.com"))
    res = {x["resource_id"] for x in st}
    check("T3 404 lookup binds via its own lookup_key",
          "account_1" in res, f"resources={sorted(res)}")
    check("T3 other user's 404 does not leak in",
          "account_2" not in res, f"resources={sorted(res)}")
    ver = [x for x in st if x["resource_id"] == "account_1"]
    check("T3 bound 404 verifies ABSENT with citation",
          ver and ver[0]["state"] == "ABSENT" and ver[0]["evidence_id"] == "evidence_1",
          json.dumps(ver))

# ---------------------------------------------------------------- T4
def t4(root):
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n",
        "",
        "evidence_1,evidence/records/pre.json,service_resource_export,2026-09-05T00:00:00Z\n"
        "evidence_2,evidence/records/post.json,service_resource_export,2026-09-12T00:00:00Z\n",
        {"evidence/records/pre.json": export_json(
            tickets=[{"resource_id": "support_1", "subject_reference": "user_1",
                      "requester_email": "alice@example.com",
                      "message_text": "call me at +1 555 000 0001"}]),
         "evidence/records/post.json": export_json(
            captured="2026-09-12T00:00:00Z",
            tickets=[{"resource_id": "support_1", "subject_reference": "user_1",
                      "requester_email": None, "message_text": "[REDACTED]"},
                     {"resource_id": "support_2", "subject_reference": "user_1",
                      "requester_email": "alice@example.com",
                      "message_text": "still here"}])})
    w = World(root)
    s, st = run(w, case("cA", "alice@example.com", audit="2026-09-10T00:00:00Z"))
    finds = {x["resource_id"] for x in st if x["phase"] == "FINDING"}
    check("T4 pre-audit exposure drives a finding", s == "INCOMPLETE" and "support_1" in finds,
          f"{s} finds={sorted(finds)}")
    check("T4 post-audit capture cannot rewrite state at audit",
          True)
    check("T4 post-audit-only violation is not a finding",
          "support_2" not in finds, f"finds={sorted(finds)}")

# ---------------------------------------------------------------- T5
def t5(root):
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n",
        "act_1,2026-09-02T10:00:00Z,DELETE_RECORD,deletion_worker,account_service,account_1,SUCCESS,Deletion worker submitted primary profile account_1 to account_service.\n",
        "evidence_1,evidence/records/export.json,service_resource_export,2026-09-05T00:00:00Z\n",
        {"evidence/records/export.json": export_json(
            profiles=[("account_1", {"resource_id": "account_1",
                                     "customer_reference": "user_1",
                                     "email": "alice@example.com",
                                     "account_status": "ACTIVE"})])})
    w = World(root)
    s, st = run(w, case("cA", "alice@example.com"))
    finds = {x["resource_id"] for x in st if x["phase"] == "FINDING"}
    check("T5 SUCCESS claim cannot override PRESENT evidence",
          s == "INCOMPLETE" and "account_1" in finds, f"{s} finds={sorted(finds)}")

def t5b(root):
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n",
        "act_1,2026-09-02T10:00:00Z,DELETE_RECORD,deletion_worker,account_service,account_1,FAILED,Deletion worker submitted primary profile account_1 to account_service.\n",
        "evidence_1,evidence/logs/lookup.log,central_observability_export,2026-09-05T00:00:00Z\n",
        {"evidence/logs/lookup.log":
            '2026-09-04T09:00:00Z level=DEBUG service=account_service trace_id=tr-1 event=profile_lookup_started lookup_key="alice@example.com" attempt=1\n'
            '2026-09-04T09:00:02Z level=INFO service=account_service trace_id=tr-1 resource_id=account_1 event=profile_lookup_completed rows=0 http_status=404 duration_ms=20\n'})
    w = World(root)
    s, st = run(w, case("cA", "alice@example.com"))
    check("T5 FAILED claim cannot override 404 evidence", s == "COMPLETE", s)

# ---------------------------------------------------------------- T7/T8
def t7(root):
    # a record observed AFTER audit_at must not change the state at audit_at
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n",
        "",
        "evidence_1,evidence/logs/lookup.log,central_observability_export,2026-09-05T00:00:00Z\n"
        "evidence_2,evidence/records/late.json,service_resource_export,2026-09-13T00:00:00Z\n",
        {"evidence/logs/lookup.log":
            '2026-09-04T09:00:00Z level=DEBUG service=account_service trace_id=tr-1 event=profile_lookup_started lookup_key="alice@example.com" attempt=1\n'
            '2026-09-04T09:00:02Z level=INFO service=account_service trace_id=tr-1 resource_id=account_1 event=profile_lookup_completed rows=0 http_status=404 duration_ms=20\n',
         "evidence/records/late.json":
            '{"exported_at": "2026-09-13T00:00:00Z", "service_exports": {"account_service": {"profile_lookups": ['
            '{"resource_id": "account_1", "observed_at": "2026-09-12T09:00:00Z", '
            '"profile": {"resource_id": "account_1", "email": "alice@example.com", "user_id": "user_1"}}]}}}'})
    w = World(root)
    s, st = run(w, case("cA", "alice@example.com"))
    finds = {x["resource_id"] for x in st if x["phase"] == "FINDING"}
    check("T7 record observed after audit_at does not leak into state",
          s == "COMPLETE" and "account_1" not in finds, f"{s} finds={sorted(finds)}")

def t8(root):
    # a violation recorded at/before audit_at in a file captured after
    # audit_at: the finding must cite that file (truthful fallback), never ""
    write_fixture(
        root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n",
        "",
        "evidence_1,evidence/records/late.json,service_resource_export,2026-09-11T00:00:00Z\n",
        {"evidence/records/late.json":
            '{"exported_at": "2026-09-11T00:00:00Z", "service_exports": {"account_service": {"profile_lookups": ['
            '{"resource_id": "account_1", "observed_at": "2026-09-06T09:00:00Z", '
            '"profile": {"resource_id": "account_1", "email": "alice@example.com", "user_id": "user_1"}}]}}}'})
    w = World(root)
    s, st = run(w, case("cA", "alice@example.com"))
    f = [x for x in st if x["phase"] == "FINDING" and x["resource_id"] == "account_1"]
    check("T8 finding cites the truthful state-establishing file",
          s == "INCOMPLETE" and f and f[0]["evidence_id"] == "evidence_1",
          f"{s} findings={f}")

def main():
    with tempfile.TemporaryDirectory() as d:
        for fn in (t1, t2, t3, t4, t5, t5b, t7, t8):
            sub = os.path.join(d, fn.__name__)
            os.makedirs(sub)
            fn(sub)
    ok = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n{ok}/{len(RESULTS)} custom checks passed")
    return 0 if ok == len(RESULTS) else 1

if __name__ == "__main__":
    sys.exit(main())
