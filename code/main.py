#!/usr/bin/env python3
"""Ghost Data Still Exists - deletion-audit agent.

Reads dataset/ and writes output.csv (case_id,deletion_status,steps_json)
at the repository root: one row per request in dataset/deletion_requests.csv.

Usage: python3 code/main.py [dataset_dir] [output_csv]
"""
import csv, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit.engine import World, CaseAudit

def case_sort_key(case_id):
    m = re.match(r"case_(\d+)$", case_id)
    return (0, int(m.group(1))) if m else (1, case_id)

def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ds = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "dataset")
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(root, "output.csv")
    # media sidecars are regenerable and gitignored: rebuild them on a
    # fresh checkout so the run is self-contained
    import subprocess
    extracted = os.path.join(root, "code", "extracted")
    manifest = os.path.join(ds, "evidence_files.csv")
    need = []
    if os.path.exists(manifest):
        with open(manifest) as f:
            for r in csv.DictReader(f):
                if not re.search(r"\.(png|jpg|jpeg|pdf)$", r["file_path"], re.I):
                    continue
                if not os.path.exists(os.path.join(extracted, r["file_id"] + ".json")):
                    need.append(r["file_id"])
    if need:
        subprocess.run([sys.executable,
                        os.path.join(root, "code", "extract_media.py"),
                        ds, extracted], check=False)
    world = World(ds)
    with open(os.path.join(ds, "deletion_requests.csv")) as f:
        cases = list(csv.DictReader(f))
    rows, warnings = [], []
    for case in sorted(cases, key=lambda c: case_sort_key(c["case_id"])):
        audit = CaseAudit(world, case)
        status, steps = audit.run()
        if status == "NOT_APPLICABLE":
            steps_json = "[]"
        else:
            steps_json = json.dumps(steps, sort_keys=True)
            if status != "COMPLETE" and audit.uid is None:
                warnings.append(f"{case['case_id']}: request email did not resolve "
                                f"to a known user_id (audited by email identifiers)")
        rows.append({"case_id": case["case_id"], "deletion_status": status,
                     "steps_json": steps_json})
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["case_id", "deletion_status", "steps_json"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out_path}")
    for msg in warnings:
        print("WARN:", msg, file=sys.stderr)

if __name__ == "__main__":
    main()
