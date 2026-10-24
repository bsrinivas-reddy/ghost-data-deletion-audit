#!/usr/bin/env python3
"""Evaluation harness: score output.csv-style predictions against
dataset/sample_output.csv and write code/evaluation/evaluation_report.md.

Usage: python3 code/evaluation/main.py [predictions_csv]
Default predictions: output for the sample requests, produced here.
"""
import csv, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audit.engine import World, CaseAudit

def score(world, ds):
    with open(os.path.join(ds, "sample_deletion_requests.csv")) as f:
        cases = {r["case_id"]: r for r in csv.DictReader(f)}
    with open(os.path.join(ds, "sample_output.csv")) as f:
        golden = {r["case_id"]: r for r in csv.DictReader(f)}
    case_ok = step_ok = field_ok = field_tot = seq_ok = 0
    details = []
    for cid in sorted(cases):
        audit = CaseAudit(world, cases[cid])
        status, steps = audit.run()
        g = golden[cid]
        gsteps = json.loads(g["steps_json"])
        norm = lambda s: {k: s[k] for k in ("phase","system_id","resource_id","operation","state","evidence_id")}
        pred_n = [norm(s) for s in steps]
        gold_n = [norm(s) for s in gsteps]
        status_ok = status == g["deletion_status"]
        case_ok += status_ok
        fields = sum(1 for s in pred_n for k in s if k != "step_no")
        matched = 0
        used = [False]*len(pred_n)
        for gs in gold_n:
            for i, ps in enumerate(pred_n):
                if not used[i] and ps == gs:
                    used[i] = True; matched += 1; break
        field_tot += max(len(gold_n), len(pred_n))
        step_ok += matched
        if pred_n == gold_n: seq_ok += 1
        details.append((cid, status_ok, matched, len(gold_n), len(pred_n),
                        pred_n == gold_n, status, g["deletion_status"]))
    n = len(cases)
    return {
        "n": n, "case_accuracy": case_ok/n,
        "status_matches": case_ok,
        "step_accuracy": step_ok/field_tot if field_tot else 1.0,
        "steps_matched": step_ok, "steps_total": field_tot,
        "sequence_accuracy": seq_ok/n, "details": details,
    }

def main():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ds = os.path.join(root, "dataset")
    world = World(ds)
    res = score(world, ds)
    print(f"cases: {res['status_matches']}/{res['n']} status correct "
          f"({res['case_accuracy']:.1%})")
    print(f"steps: {res['steps_matched']}/{res['steps_total']} matched "
          f"({res['step_accuracy']:.1%}), sequence-perfect cases: "
          f"{sum(1 for d in res['details'] if d[5])}/{res['n']}")
    for cid, ok, m, gl, pl, seq, ps, gs in res["details"]:
        flag = "OK " if (ok and seq) else ("~  " if ok else "X  ")
        print(f"{flag}{cid}: status {ps} vs {gs}; steps {m}/{max(gl,pl)}; seq {'exact' if seq else 'diff'}")

if __name__ == "__main__":
    main()
