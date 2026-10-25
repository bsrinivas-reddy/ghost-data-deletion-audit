"""Mock-backend tests for the optional model-assist pipeline.

These tests exercise prompt routing, response parsing, usage logging and
report aggregation WITHOUT any live model call (backend "mock" simulates
responses and token counts and is labeled as such in the log). The live
gemini path is NOT covered here: it requires the user's own API key and
has not been live-verified by the author; it is exercised only when the
user runs with GEMINI_API_KEY set.
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_assist as m

def main():
    checks = []
    tmp = tempfile.mkdtemp()
    m.USAGE_LOG = os.path.join(tmp, "usage_log.jsonl")

    # none backend: no calls, no log
    assert m.assist("intent", "please delete my account", backend="none") is None
    checks.append(("none backend performs no call", not os.path.exists(m.USAGE_LOG)))

    # mock intent
    ans = m.assist("intent", "please delete my account", backend="mock")
    checks.append(("mock intent returns canned verdict", ans == "DELETION"))

    # mock verify via run_verification
    out_csv = os.path.join(tmp, "out.csv")
    with open(out_csv, "w") as f:
        f.write("case_id,deletion_status,steps_json\n")
        f.write('case_x,COMPLETE,"[]"\n')
    vs = m.run_verification(out_csv, "mock", limit=1)
    checks.append(("mock verify reviews 1 case", len(vs) == 1 and vs[0]["verdict"] == "CONSISTENT"))

    # usage log written, mock separated from real totals
    u = m.summarize_usage(m.USAGE_LOG)
    checks.append(("mock calls logged", u["mock_calls"] == 2))
    checks.append(("mock excluded from real usage totals",
                   u["total_calls"] == 0 and u["total_prompt_tokens"] == 0))

    # gemini backend without key: skipped, no call, no crash
    os.environ.pop("GEMINI_API_KEY", None)
    assert m.assist("intent", "x", backend="gemini") is None
    u = m.summarize_usage(m.USAGE_LOG)
    checks.append(("gemini without key skips and logs nothing real", u["total_calls"] == 0))

    original_assist = m.assist
    captured = []
    def fake_assist(task, text, **kwargs):
        captured.append(kwargs)
        return ""
    m.assist = fake_assist
    try:
        vs = m.run_verification(out_csv, "mock", limit=1)
        checks.append(("empty verification response is unparsed", vs[0]["verdict"] == "UNPARSED"))
        import csv
        large = [{"detail":"x" * 6500}]
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["case_id","deletion_status","steps_json"])
            w.writeheader(); w.writerow({"case_id":"case_large","deletion_status":"INCOMPLETE","steps_json":json.dumps(large)})
        captured.clear()
        vs = m.run_verification(out_csv, "mock", limit=1)
        checks.append(("oversized plan is skipped without partial JSON disclosure", not captured and vs[0]["verdict"] == "SKIPPED_OVERSIZE"))
        captured.clear()
        try:
            m.run_verification(out_csv, "mock", limit=0)
        except ValueError:
            checks.append(("zero call limit is rejected before any call", not captured))
        else:
            checks.append(("zero call limit is rejected before any call", False))
        for invalid in (True, False, -1, 2.5, "2"):
            try:
                m.run_verification("nonexistent-input.csv", "mock", limit=invalid)
            except ValueError:
                checks.append((f"invalid limit rejected before file read {invalid!r}", True))
            else:
                checks.append((f"invalid limit rejected before file read {invalid!r}", False))
        for size in (6000,6001):
            plan=[{"detail":""}]
            plan[0]["detail"]="x" * (size-len(json.dumps(plan)))
            with open(out_csv,"w",newline="") as f:
                w=csv.DictWriter(f,fieldnames=["case_id","deletion_status","steps_json"])
                w.writeheader();w.writerow({"case_id":"boundary","deletion_status":"INCOMPLETE","steps_json":json.dumps(plan)})
            captured.clear()
            vs=m.run_verification(out_csv,"mock",limit=1)
            checks.append((f"exact plan size boundary {size}",bool(captured) == (size==6000) and
                           vs[0]["verdict"] == ("UNPARSED" if size==6000 else "SKIPPED_OVERSIZE") and
                           vs[0]["status"] == "INCOMPLETE"))
        with open(out_csv,"w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["case_id","deletion_status","steps_json"])
            w.writeheader();w.writerows({"case_id":f"case_{n}","deletion_status":"COMPLETE","steps_json":"[]"} for n in range(3))
        for response,want in ((" \n ","UNPARSED"),("CONSISTENT","CONSISTENT"),("inconsistent","INCONSISTENT")):
            m.assist=lambda *args,**kwargs:response
            vs=m.run_verification(out_csv,"mock",limit=2)
            checks.append((f"verification response control {want}",len(vs)==2 and all(x["verdict"]==want for x in vs)))
        before=open(out_csv,"rb").read()
        m.run_verification(out_csv,"mock",limit=None,out_path=os.path.join(tmp,"annotations.json"))
        checks.append(("advisory output preserves prediction bytes",open(out_csv,"rb").read()==before))
    finally:
        m.assist = original_assist

    import subprocess
    cli=subprocess.run([sys.executable,m.__file__,"verify",out_csv,"none","1"],capture_output=True,text=True)
    checks.append(("disabled CLI reports no reviewed cases",cli.returncode==0 and "0 cases reviewed | skipped: 0" in cli.stdout))
    with open(out_csv,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["case_id","deletion_status","steps_json"])
        w.writeheader();w.writerow({"case_id":"large","deletion_status":"COMPLETE","steps_json":json.dumps([{"detail":"x"*6500}])})
    cli=subprocess.run([sys.executable,m.__file__,"verify",out_csv,"none","1"],capture_output=True,text=True)
    checks.append(("CLI does not count skipped plan as reviewed",cli.returncode==0 and "0 cases reviewed | skipped: 1" in cli.stdout))

    bad = 0
    for name, ok in checks:
        print(("PASS" if ok else "FAIL"), name)
        bad += 0 if ok else 1
    print(f"\n{len(checks)-bad}/{len(checks)} model-assist checks passed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
