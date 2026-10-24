"""Independent semantic coverage audit of output.csv against the challenge
contract (problem_statement.md), not against the golden samples.

Checks the output an auditor should be able to defend:
  - schema and ordering rules (phases, operation table order, ids)
  - COMPLETE rows: verification-only, every step cites evidence
  - INCOMPLETE rows: cited findings, uncited remediation, full
    remediation + verification coverage of every footprint resource
  - NOT_APPLICABLE rows: empty steps
  - only legal (operation, state) pairs from the spec table
  - cited evidence ids exist in the dataset manifest or activity/audit logs
Usage: python3 code/evaluation/semantic_audit.py [output.csv]
"""
import csv, json, re, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DS = os.environ.get("DATASET", os.path.join(ROOT, "dataset"))

SPEC_ORDER = [
    ("REPORT_REMAINING_RECORD", "PRESENT"), ("REPORT_EXPOSED_PII", "PRESENT"),
    ("REPORT_ACTIVE_DATA_FLOW", "ACTIVE"), ("REPORT_RESTORE_RISK", "ACTIVE"),
    ("DISABLE_DATA_FLOW", "DISABLED"), ("BLOCK_RESTORE", "BLOCKED"),
    ("DELETE_RECORD", "ABSENT"), ("REDACT_RECORD", "REDACTED"),
    ("ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFY_RECORD_ABSENT", "ABSENT"), ("VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFY_RESTORE_BLOCKED", "BLOCKED"),
]
LEGAL = set(SPEC_ORDER)
PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OP_ORDER = [op for op, _ in SPEC_ORDER]
# policy: finding operation -> required remediation + verification operations
COVERAGE = {
    "REPORT_REMAINING_RECORD": ("DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    "REPORT_EXPOSED_PII": (None, None),   # redact or anonymize by category
    "REPORT_ACTIVE_DATA_FLOW": ("DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
    "REPORT_RESTORE_RISK": ("BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
}

def main(path):
    manifest = set()
    evidence_times = {}
    with open(os.path.join(DS, "evidence_files.csv")) as f:
        for r in csv.DictReader(f):
            manifest.add(r["file_id"])
            evidence_times[r["file_id"]] = r["captured_at"]
    for filename, idcol in (("system_activity.csv", "activity_id"), ("user_audit_log.csv", "audit_id")):
        with open(os.path.join(DS, filename)) as f:
            for r in csv.DictReader(f):
                evidence_times[r[idcol]] = r["event_time"]
    reqs = list(csv.DictReader(open(os.path.join(DS, "deletion_requests.csv"))))
    reader = csv.DictReader(open(path))
    rows = list(reader)
    problems = []
    if reader.fieldnames != ["case_id", "deletion_status", "steps_json"]:
        problems.append(("SCHEMA", "header differs from exact three-column contract"))

    # row contract
    def key(cid):
        m = re.fullmatch(r"case_(\d+)", cid)
        return (0, int(m.group(1))) if m else (1, cid)
    want_order = sorted((r["case_id"] for r in reqs), key=key)
    audit_times = {r["case_id"]: r["audit_at"] for r in reqs}
    if [r["case_id"] for r in rows] != want_order:
        problems.append(("ROWSET", "rows not sorted by case_id or row set differs"))
    if len(rows) != len(reqs):
        problems.append(("ROWSET", f"{len(rows)} rows for {len(reqs)} requests"))

    for r in rows:
        cid = r["case_id"]
        try:
            steps = json.loads(r["steps_json"])
        except ValueError:
            problems.append((cid, "steps_json is not valid JSON")); continue
        if not isinstance(steps, list) or any(not isinstance(s, dict) for s in steps):
            problems.append((cid, "steps_json must be an array of objects")); continue
        required = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
        if any(set(s) != required or any(not isinstance(s[k], str) for k in required - {"step_no"})
               or type(s["step_no"]) is not int for s in steps):
            problems.append((cid, "step fields/types differ from exact contract")); continue
        status = r["deletion_status"]
        if status not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
            problems.append((cid, f"illegal status {status}")); continue
        if status == "NOT_APPLICABLE":
            if steps != []: problems.append((cid, "NOT_APPLICABLE with non-empty steps"))
            continue
        # step_no consecutive
        if [s.get("step_no") for s in steps] != list(range(1, len(steps) + 1)):
            problems.append((cid, "step_no not consecutive from 1"))
        # legal pairs + ordering
        sort_key = []
        for s in steps:
            if (s.get("operation"), s.get("state")) not in LEGAL:
                problems.append((cid, f"illegal op/state {s.get('operation')}/{s.get('state')}"))
            operation = s.get("operation", "")
            expected_phase = "VERIFICATION" if operation.startswith("VERIFY_") else "FINDING" if operation.startswith("REPORT_") else "REMEDIATION"
            if s.get("phase") != expected_phase:
                problems.append((cid, f"operation {operation} in wrong phase"))
            sort_key.append((PHASE_ORDER.get(s.get("phase"), 9),
                             OP_ORDER.index(s["operation"]) if s.get("operation") in OP_ORDER else 99,
                             s.get("system_id", ""), s.get("resource_id", "")))
        if sort_key != sorted(sort_key):
            problems.append((cid, "step ordering violates phase/op/system/resource order"))
        findings = [s for s in steps if s["phase"] == "FINDING"]
        remed = [s for s in steps if s["phase"] == "REMEDIATION"]
        verif = [s for s in steps if s["phase"] == "VERIFICATION"]
        if status == "COMPLETE":
            if not steps:
                problems.append((cid, "COMPLETE without any state proof"))
            if findings or remed:
                problems.append((cid, "COMPLETE with non-verification steps"))
            for s in steps:
                if not s.get("evidence_id"):
                    problems.append((cid, "COMPLETE step without cited evidence"))
        else:
            if not findings:
                problems.append((cid, "INCOMPLETE without findings"))
            for s in findings:
                if not s.get("evidence_id"):
                    problems.append((cid, "finding without cited evidence"))
            # INCOMPLETE remediation and future-verification steps are
            # REQUIRED by the spec to carry an empty evidence_id
            for s in verif:
                if s.get("evidence_id"):
                    problems.append((cid, "INCOMPLETE future verification carrying evidence_id"))
            for s in remed:
                if s.get("evidence_id"):
                    problems.append((cid, "remediation step carrying evidence_id"))
            # coverage: every finding resource has remediation + verification
            rem_ops = {}
            for s in remed: rem_ops.setdefault((s["system_id"], s["resource_id"]), set()).add(s["operation"])
            ver_ops = {}
            for s in verif: ver_ops.setdefault((s["system_id"], s["resource_id"]), set()).add(s["operation"])
            for fstep in findings:
                rid = (fstep["system_id"], fstep["resource_id"])
                need_r, need_v = COVERAGE[fstep["operation"]]
                if need_r is None:  # exposed PII: redact or anonymize
                    ok_r = bool(rem_ops.get(rid, set()) & {"REDACT_RECORD", "ANONYMIZE_RECORD"})
                    ok_v = bool(ver_ops.get(rid, set()) & {"VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED"})
                else:
                    ok_r = need_r in rem_ops.get(rid, set())
                    ok_v = need_v in ver_ops.get(rid, set())
                if not ok_r: problems.append((cid, f"finding {rid} lacks remediation"))
                if not ok_v: problems.append((cid, f"finding {rid} lacks verification"))
        # cited evidence exists
        for s in steps:
            ev = s.get("evidence_id") or ""
            if ev and ev not in evidence_times:
                problems.append((cid, f"cited evidence {ev} not in manifest/activity/audit"))
            if ev in evidence_times and evidence_times[ev] > audit_times.get(cid, ""):
                problems.append((cid, f"post-audit citation {ev}"))

    by = {}
    for cid, msg in problems:
        by.setdefault(msg, []).append(cid)
    print(f"semantic audit: {len(rows)} rows, {len(problems)} problems in {len(by)} classes")
    for msg, cids in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{len(cids):4d}x] {msg} (e.g. {cids[:3]})")
    return 0 if not problems else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "output.csv")))
