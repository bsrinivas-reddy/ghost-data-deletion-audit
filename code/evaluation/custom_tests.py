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
  T8 post-audit captures are inadmissible even with earlier record times
  T9 future-dated records are not clamped to the capture date
  T10 missing retained records and empty footprints fail closed

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
    import shutil
    shutil.copyfile(os.path.join(os.path.dirname(__file__), "..", "..", "dataset", "deletion_rules.csv"), os.path.join(root, "deletion_rules.csv"))
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
          any(x["resource_id"] == "support_1" and x["phase"] == "FINDING"
              and x["evidence_id"] == "evidence_1" for x in st))
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
    # Earlier record time does not make a post-audit capture admissible.
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
    check("T8 post-audit capture is inadmissible even with an earlier record timestamp",
          not f and not any(x["evidence_id"] == "evidence_1" for x in st),
          f"{s} findings={f}")

def t9(root):
    t7(root)
    p = os.path.join(root, "evidence_files.csv")
    text = open(p).read().replace("2026-09-13T00:00:00Z", "2026-09-05T00:00:00Z")
    open(p, "w").write(text)
    w = World(root)
    status, steps = run(w, case("cA", "alice@example.com"))
    check("T9 future-dated record in an earlier capture is not clamped into the past",
          status == "COMPLETE" and not any(x["phase"] == "FINDING" for x in steps))

def t10(root):
    from audit.model import Observation, ABSENT, CAT_SECURITY
    write_fixture(root, "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    w = World(root)
    audit = CaseAudit(w, case("cA", "alice@example.com"))
    status, steps = audit.run()
    check("T10 no evidence does not certify COMPLETE", status == "INCOMPLETE" and steps == [] and bool(audit.issues))
    w.obs.append(Observation("evidence_1", "evidence", "2026-09-05T00:00:00Z", "2026-09-05T00:00:00Z",
                             "security_service", "audit_record_1", CAT_SECURITY, ABSENT,
                             user_ids=frozenset({"user_1"})))
    audit = CaseAudit(w, case("cA", "alice@example.com"))
    status, steps = audit.run()
    check("T10 absent mandatory retained record is unresolved, not COMPLETE",
          status == "INCOMPLETE" and any("required retained record" in m for m in audit.issues)
          and not any(s["phase"] == "REMEDIATION" for s in steps))

def t11(root):
    write_fixture(root, "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-09-12T00:00:00Z\n", "",
        "evidence_1,evidence/records/pre.json,service_resource_export,2026-09-05T00:00:00Z\n",
        {"evidence/records/pre.json": export_json(profiles=[("account_1", {"resource_id": "account_1", "customer_reference": "user_1", "email": "other@example.com"})])},
        "audit_1,user_1,2026-09-12T00:00:00Z,email,alice@example.com,other@example.com\n")
    w = World(root)
    a = CaseAudit(w, case("cA", "alice@example.com"))
    _, steps = a.run()
    check("T11 future identity snapshot or change does not bind resources", a.uid is None and steps == [])


def t12(root):
    bundle = {"snapshots": [{"captured_at": "2026-09-05T00:00:00Z", "data_store": "privacy_treatment_service",
        "collection": "operational_record_history", "records": [{"recorded_at": "2026-09-04T00:00:00Z",
        "system": "account_service", "resource_id": "account_1", "record_type": "USER_PROFILE", "result": "NOT_FOUND", "lookup_value": "alice@example.com"}]}]}
    write_fixture(root, "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "",
        "evidence_1,evidence/records/pre.json,records_assurance_snapshot_bundle,2026-09-05T00:00:00Z\n",
        {"evidence/records/pre.json": json.dumps(bundle)})
    w = World(root)
    status, steps = run(w, case("cA", "alice@example.com"))
    check("T12 nested operational history uses its own system, result and record time",
          status == "COMPLETE" and len(steps) == 1 and steps[0]["system_id"] == "account_service"
          and steps[0]["state"] == "ABSENT" and steps[0]["evidence_id"] == "evidence_1")

def t13(root):
    from unittest.mock import patch
    from extract_media import extract_text
    with patch("subprocess.run", side_effect=FileNotFoundError("tesseract")):
        try:
            extract_text("missing.png")
        except RuntimeError:
            caught = True
        else:
            caught = False
    check("T13 unavailable OCR fails loudly instead of dropping media evidence", caught)

def t14(root):
    write_fixture(root, "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n",
        "act_1,2026-09-05T00:00:00Z,LINK_RESOURCE_IDENTITY,data_catalog,export_service,export_1,SUCCESS,Data catalog linked export_1 (DOC-1234) to alice@example.com and user_1.\n",
        "evidence_1,evidence/doc.pdf,customer_statement,2026-09-04T00:00:00Z\n", {})
    extracted = os.path.join(root, "extracted")
    os.makedirs(extracted)
    with open(os.path.join(extracted, "evidence_1.json"), "w") as f:
        json.dump({"records": [], "text": "CUSTOMER STATEMENT DOC-1234"}, f)
    w = World(root, extracted)
    a = CaseAudit(w, case("cA", "alice@example.com"))
    status, steps = a.run()
    check("T14 catalog document alias supplies resource state from the artifact",
          status == "INCOMPLETE" and any(s["phase"] == "FINDING" and s["evidence_id"] == "evidence_1" for s in steps) and not a.issues)
    a = CaseAudit(w, case("cA", "alice@example.com", audit="2026-09-04T12:00:00Z"))
    _, steps = a.run()
    check("T14 future catalog alias cannot retroactively bind the document", steps == [])

def t15(root):
    from audit.model import Observation, ABSENT, PRESENT, CAT_PROFILE
    write_fixture(root, "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    w = World(root)
    w.obs = [Observation("replica", "evidence", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z",
        "account_service", "account_1", CAT_PROFILE, PRESENT, user_ids=frozenset({"user_1"}), store_id="eu_replica"),
        Observation("primary", "evidence", "2026-09-05T00:00:00Z", "2026-09-05T00:00:00Z",
        "account_service", "account_1", CAT_PROFILE, ABSENT, store_id="primary")]
    status, steps = run(w, case("cA", "alice@example.com"))
    check("T15 a newer clean primary cannot hide a stale residual replica",
          status == "INCOMPLETE" and any(x["phase"] == "FINDING" and x["evidence_id"] == "replica" for x in steps))
    w.obs.append(Observation("replica_clean", "evidence", "2026-09-06T00:00:00Z", "2026-09-06T00:00:00Z",
        "account_service", "account_1", CAT_PROFILE, ABSENT, store_id="eu_replica"))
    status, steps = run(w, case("cA", "alice@example.com"))
    check("T15 completion requires every observed copy to be compliant", status == "COMPLETE" and steps[0]["evidence_id"] == "replica_clean")


def t16(root):
    from audit.parsers import parse_sql_file
    sql = "CREATE TABLE snapshot_scope(origin_system TEXT,captured_at TEXT); INSERT INTO snapshot_scope VALUES('account_service','2026-09-05T00:00:00Z'); CREATE TABLE customer_profiles(resource_id TEXT,email TEXT); CREATE TABLE customer_search_documents(resource_id TEXT,email TEXT);"
    write_fixture(root, "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "",
                  "evidence_1,evidence/scoped.sql,database_inventory,2026-09-05T00:00:00Z\n", {"evidence/scoped.sql": sql})
    w = World(root)
    check("T16 empty scoped table is an absence capture, unscoped table is not",
          len(w.captures) == 1 and w.captures[0].system_id == "account_service" and not w.captures[0].resource_ids)
    from audit.model import Observation, CAT_PROFILE, CAT_SEARCH, PRESENT
    for system, category, rid in [("account_service", CAT_PROFILE, "account_1"), ("search_service", CAT_SEARCH, "search_1")]:
        w.obs.append(Observation("before", "evidence", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z", system,rid,category,PRESENT,
                                 user_ids=frozenset({"user_1"}),store_id="primary"))
    status, steps = run(w, case("cA", "alice@example.com"))
    findings = {x["resource_id"] for x in steps if x["phase"] == "FINDING"}
    check("T16 scoped absence clears only its own service", status == "INCOMPLETE" and findings == {"search_1"})


def t17(root):
    from audit.model import Observation, CAT_SECURITY, RETAINED
    write_fixture(root,"user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    w = World(root)
    w.obs = [Observation("retention", "evidence", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z", "security_service", "audit_record_1", CAT_SECURITY, RETAINED,
                         user_ids=frozenset({"user_1"}), attributes={"retention_until": "2026-09-06T00:00:00Z"})]
    a = CaseAudit(w, case("cA","alice@example.com",audit="2026-09-05T00:00:00Z"))
    check("T17 retained record is compliant while its retention period is active", a.run()[0] == "COMPLETE" and not a.issues)
    a = CaseAudit(w, case("cA","alice@example.com",audit="2026-09-10T00:00:00Z"))
    check("T17 expired conditional retention does not invent a default delete rule",
          a.run()[0] == "INCOMPLETE" and any("expired" in msg for msg in a.issues))

def t18(root):
    write_fixture(root,
        "user_1,Alice A,shared@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n"
        "user_2,Bob B,shared@example.com,+1 555 000 0002,,2026-01-01T00:00:00Z\n", "",
        "evidence_1,evidence/pre.json,service_resource_export,2026-09-05T00:00:00Z\n",
        {"evidence/pre.json":export_json(profiles=[("account_2", {"resource_id":"account_2", "customer_reference":"user_2", "email":"shared@example.com"})])})
    a = CaseAudit(World(root),case("cA","shared@example.com"))
    status, steps = a.run()
    check("T18 reused email does not bind either owner's resource",status == "INCOMPLETE" and not steps and any("multiple" in msg for msg in a.issues))

def t19(root):
    write_fixture(root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n"
        "user_2,Bob B,bob@example.com,+1 555 000 0002,,2026-01-01T00:00:00Z\n", "",
        "evidence_1,evidence/pre.json,service_resource_export,2026-09-05T00:00:00Z\n"
        "evidence_2,evidence/post.json,service_resource_export,2026-09-06T00:00:00Z\n",
        {"evidence/pre.json":export_json(profiles=[("account_1", {"resource_id":"account_1", "customer_reference":"user_1", "email":"alice@example.com"})]),
         "evidence/post.json":export_json(profiles=[("account_1", {"resource_id":"account_1", "customer_reference":"user_2", "email":"bob@example.com"})],captured="2026-09-06T00:00:00Z")})
    a = CaseAudit(World(root),case("cA","alice@example.com"))
    status, steps = a.run()
    check("T19 phase-two resource reuse cannot import another owner's state",
          status == "INCOMPLETE" and any(x["phase"] == "FINDING" and x["evidence_id"] == "evidence_1" for x in steps))
    from audit.parsers import ids_from_deep
    e,u,_,_ = ids_from_deep({"requester_email":"bob@example.com","agent_email":"alice@example.com", "actor":{"email":"alice@example.com","user_id":"user_1"}})
    check("T19 actor and agent identity fields are not subject identity", e == {"bob@example.com"} and not u)

def t20(root):
    from audit.intent import classify
    check("T20 explicit negation is not deletion",classify("Please do not delete my account.") == "NOT_DELETION")
    check("T20 mixed authorization remains ambiguous",classify("Don't delete my invoices, but delete my account.") == "UNKNOWN")
    check("T20 personal-details access request does not imply erasure",classify("Show me my personal details.") != "DELETION")
    check("T20 Spanish negation does not authorize erasure",classify("No elimines mi cuenta.") == "NOT_DELETION")
    from audit.model import Observation, CAT_SECURITY, RETAINED
    write_fixture(root,"user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    w = World(root)
    w.obs = [Observation("old", "evidence", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z", "security_service", "audit_record_1", CAT_SECURITY, RETAINED,user_ids=frozenset({"user_1"}))]
    status, steps = run(w,case("cA","alice@example.com"))
    check("T20 prior compliant retention is not excluded by an invented lifecycle",status == "COMPLETE" and len(steps) == 1 and steps[0]["evidence_id"] == "old")

def t21(root):
    from audit.parsers import state_for_record, ids_from_deep
    from audit.model import CAT_SUPPORT_MSG, CAT_DATAFLOW, CAT_BACKUP, IDENTIFIABLE
    record = {"requester_name":None,"requester_email":None,"requester_phone":None,"message_text":"Please send the update to alice@example.com."}
    check("T21 redacted headers cannot hide PII in retained message text",state_for_record(CAT_SUPPORT_MSG,record) == IDENTIFIABLE)
    check("T21 embedded message email remains a subject identity anchor",ids_from_deep(record)[0] == {"alice@example.com"})
    check("T21 absent process booleans are unknown, not disabled/blocked", state_for_record(CAT_DATAFLOW,{}) == "UNKNOWN" and state_for_record(CAT_BACKUP,{}) == "UNKNOWN")

def t22(root):
    from audit.model import Observation, CAT_LEGAL, RETAINED, CAT_PROFILE, PRESENT
    write_fixture(root,"user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    w = World(root)
    w.obs = [Observation("hold", "evidence", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z", "legal_service", "legal_hold_1", CAT_LEGAL, RETAINED,
                         user_ids=frozenset({"user_1"}),attributes={"hold_active":False})]
    a = CaseAudit(w,case("cA","alice@example.com"))
    check("T22 inactive legal hold is unresolved without an explicit fallback rule",a.run()[0] == "INCOMPLETE" and any("inactive" in msg for msg in a.issues))
    w.obs = [Observation("profile", "evidence", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z", "account_service", "account_1", CAT_PROFILE, PRESENT,user_ids=frozenset({"user_1"}))]
    w.rules[CAT_PROFILE]["required_action"] = "RETAIN"
    a = CaseAudit(w,case("cA","alice@example.com"))
    status, steps = a.run()
    check("T22 policy input change cannot silently execute old category constants",status == "INCOMPLETE" and not steps and any("differs" in msg for msg in a.issues))

def t23(root):
    import contextlib, io
    from evaluation import semantic_audit as validator
    write_fixture(root,"user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    with open(os.path.join(root,"deletion_requests.csv"),"w") as f:
        f.write("case_id,audit_at\ncase_1,2026-09-10T00:00:00Z\n")
    out = os.path.join(root,"output.csv")
    old = validator.DS
    validator.DS = root
    try:
        for value in ["{}", "[1]", '[{"step_no":1}]']:
            with open(out,"w",newline="") as f:
                writer=csv.writer(f);writer.writerow(["case_id","deletion_status","steps_json"]);writer.writerow(["case_1","COMPLETE",value])
            with contextlib.redirect_stdout(io.StringIO()):
                result = validator.main(out)
            check("T23 malformed plan rejected without validator crash: " + value,result == 1)
    finally:
        validator.DS = old

def t24(root):
    from audit.model import Observation, CAT_TOMBSTONE, ABSENT
    write_fixture(root,"user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "", "", {})
    w = World(root)
    w.obs = [Observation("missing", "evidence", "2026-09-04T00:00:00Z", "2026-09-04T00:00:00Z", "identity_service", "tombstone_1", CAT_TOMBSTONE, ABSENT,user_ids=frozenset({"user_1"}))]
    a = CaseAudit(w,case("cA","alice@example.com"))
    status, steps = a.run()
    check("T24 absent required tombstone is not certified as redacted",status == "INCOMPLETE" and any("preserved record is absent" in msg for msg in a.issues)
          and not any(s["phase"] in ("FINDING","REMEDIATION") for s in steps))

def t25(root):
    log = (
        '2026-09-04T09:00:00Z level=DEBUG service=account_service trace_id=shared event=profile_lookup_started lookup_key="alice@example.com"\n'
        '2026-09-04T09:00:01Z level=DEBUG service=support_platform trace_id=shared event=support_ticket_read_started lookup_key="bob@example.com"\n'
        '2026-09-04T09:00:02Z level=INFO service=account_service trace_id=shared resource_id=account_1 event=profile_lookup_completed rows=0 http_status=404\n')
    write_fixture(root,
        "user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n"
        "user_2,Bob B,bob@example.com,+1 555 000 0002,,2026-01-01T00:00:00Z\n", "",
        "evidence_1,evidence/trace.log,central_observability_export,2026-09-05T00:00:00Z\n", {"evidence/trace.log":log})
    w = World(root)
    a = CaseAudit(w,case("cA","alice@example.com"))
    b = CaseAudit(w,case("cB","bob@example.com"))
    _, alice = a.run();_, bob = b.run()
    check("T25 trace correlation is service-scoped",any(s["resource_id"] == "account_1" for s in alice) and not any(s["resource_id"] == "account_1" for s in bob))

def t26(root):
    payload = export_json(search=[{"resource_id":"search_1","query":"alice@example.com", "hits":{"total":1,"documents":[{"resource_id":"search_1","email":"alice@example.com"}]}}])
    write_fixture(root,"user_1,Alice A,alice@example.com,+1 555 000 0001,,2026-01-01T00:00:00Z\n", "",
                  "evidence_1,evidence/search.json,service_resource_export,2026-09-05T00:00:00Z\n", {"evidence/search.json":payload})
    status,steps=run(World(root),case("cA","alice@example.com"))
    check("T26 search hits payload proves presence without a result label",status == "INCOMPLETE" and any(s["phase"] == "FINDING" and s["evidence_id"] == "evidence_1" for s in steps))

def main():
    with tempfile.TemporaryDirectory() as d:
        for fn in (t1, t2, t3, t4, t5, t5b, t7, t8, t9, t10, t11, t12, t13, t14, t15, t16, t17, t18, t19, t20, t21, t22, t23, t24, t25, t26):
            sub = os.path.join(d, fn.__name__)
            os.makedirs(sub)
            fn(sub)
    ok = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n{ok}/{len(RESULTS)} custom checks passed")
    return 0 if ok == len(RESULTS) else 1

if __name__ == "__main__":
    sys.exit(main())
