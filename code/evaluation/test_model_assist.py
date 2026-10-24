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

    bad = 0
    for name, ok in checks:
        print(("PASS" if ok else "FAIL"), name)
        bad += 0 if ok else 1
    print(f"\n{len(checks)-bad}/{len(checks)} model-assist checks passed")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
