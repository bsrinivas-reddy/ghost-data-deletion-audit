#!/usr/bin/env python3
"""Optional model-assisted evidence extraction with measured usage.

The audit engine is deterministic end to end: identity resolution, footprint
reconstruction, state-at-audit, policy and step emission never depend on a
model. This module offers two optional assists on top of that core:

  intent  - second opinion on whether a request actually asks for deletion,
            consulted only when the deterministic classifier is uncertain
  media   - structure noisy OCR/PDF text into the same record schema the
            deterministic extractor emits (engine keeps citing the original
            evidence file, never the model)
  verify  - model review of each emitted audit plan (structural second
            opinion over the case's findings/remediation/verification
            steps and their citations); runs over real run output and
            records disagreements as advisory annotations only - the
            deterministic output is never rewritten by the model

  mock    - test backend: canned responses and SIMULATED token counts,
            clearly labeled mock in the usage log so tests can exercise
            the full pipeline with no network and no key. Mock entries
            are aggregated separately and never presented as model usage.

Backends:
  none    (default) no model calls; the run is fully deterministic
  gemini  Gemini API, key from GEMINI_API_KEY env var only. A free-tier key
          (Google AI Studio, 250 requests/day at the time of writing) is
          enough for the 518-case run because assists fire only where the
          deterministic path is uncertain. Alternatively run these same
          prompts inside a local Gemini/Antigravity session and record the
          usage below - either way the measured usage lands in
          evaluation/usage_log.jsonl and is summarized by usage_report.md.

Every call is logged with real token counts from the API response. No call
is ever simulated: with no key configured the assist is skipped and the log
stays empty, which usage_report.md then reports honestly as zero usage.
"""
import json, os, sys, time, urllib.request

USAGE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "usage_log.jsonl")
MODEL = "gemini-2.5-flash"

INTENT_PROMPT = """You are classifying a customer-service request for a data-deletion audit.
Decide whether the customer is actually requesting deletion of their personal data.
Answer with exactly one word: DELETION, NOT_DELETION, or AMBIGUOUS.

Request:
{text}"""

MEDIA_PROMPT = """You are structuring extracted document text for a data-deletion audit.
From the text below, identify every data-store resource id (patterns like account_123,
analytics_456, support_789, search_012, backup_345, data_flow_678, export_901,
tombstone_234, audit_record_567) and return JSON only:
{{"records": [{{"resource_id": "...", "state": "PRESENT|ABSENT|REDACTED|ANONYMIZED",
"emails": ["..."], "user_ids": ["..."], "phones": ["..."]}}]}}
Only use identifiers stated in the text. Associate an identifier with a resource only
when the text itself links them. If unsure, leave the field empty.

Text:
{text}"""

def log_call(task, backend, model, prompt_tokens, completion_tokens, note=""):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "task": task, "backend": backend, "model": model,
           "prompt_tokens": prompt_tokens,
           "completion_tokens": completion_tokens, "note": note}
    with open(USAGE_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")

def _gemini(prompt, key, model):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0}}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    text = "".join(p.get("text", "")
                   for c in data.get("candidates", [])
                   for p in c.get("content", {}).get("parts", []))
    usage = data.get("usageMetadata", {})
    return text, usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)

VERIFY_PROMPT = """You are reviewing one case from a data-deletion audit.
The deterministic auditor concluded {status} and emitted the ordered steps below
(findings cite evidence ids; remediation and future verification are uncited by design).
Check only structural consistency: do findings support the status, does every finding
have remediation and verification, are retained-record checks present where required?
Answer with exactly one word on the first line: CONSISTENT or INCONSISTENT.
Then at most one short sentence of reasoning.

Case {case_id}, status {status}:
{steps}
"""

def assist(task, text, backend="none", model=MODEL, **fmt):
    """Return the model's answer text, or None when no backend is active."""
    if backend == "none":
        return None
    if backend == "mock":
        canned = {"intent": "DELETION",
                  "media": '{"records": []}',
                  "verify": "CONSISTENT\nmock review"}[task]
        log_call(task, backend, "mock-model", len(text.split()),
                 len(canned.split()),
                 note="MOCK: pipeline test, no live model call, tokens simulated")
        return canned
    if backend == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        if task == "verify":
            prompt = VERIFY_PROMPT.format(**fmt)
        else:
            prompt = (INTENT_PROMPT if task == "intent" else MEDIA_PROMPT).format(text=text)
        answer, pt, ct = _gemini(prompt, key, model)
        log_call(task, backend, model, pt, ct)
        return answer
    raise ValueError(f"unknown backend: {backend}")

def run_verification(output_csv, backend, limit=None, out_path=None):
    """Model review pass over an existing output.csv. Advisory only:
    writes annotations, never modifies the audited output."""
    import csv as _csv
    rows = list(_csv.DictReader(open(output_csv)))
    if limit:
        rows = rows[:limit]
    verdicts = []
    for r in rows:
        steps = json.dumps(json.loads(r["steps_json"]), indent=None)
        brief = ""
        ans = assist("verify", brief, backend=backend,
                     case_id=r["case_id"], status=r["deletion_status"],
                     steps=steps[:6000])
        if ans is None:
            continue
        first = ans.strip().splitlines()[0].strip().upper()
        verdicts.append({"case_id": r["case_id"],
                         "status": r["deletion_status"],
                         "verdict": first if first in ("CONSISTENT", "INCONSISTENT") else "UNPARSED",
                         "detail": ans.strip()[:300]})
    if out_path:
        with open(out_path, "w") as f:
            json.dump(verdicts, f, indent=1)
    return verdicts

def summarize_usage(log_path=USAGE_LOG):
    """Aggregate the measured usage log for evaluation/usage_report.md."""
    calls = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            calls = [json.loads(l) for l in f if l.strip()]
    real = [c for c in calls if c.get("backend") != "mock"]
    mock = [c for c in calls if c.get("backend") == "mock"]
    by_model = {}
    for c in real:
        m = by_model.setdefault(c["model"], {"calls": 0, "prompt_tokens": 0,
                                             "completion_tokens": 0})
        m["calls"] += 1
        m["prompt_tokens"] += c["prompt_tokens"]
        m["completion_tokens"] += c["completion_tokens"]
    return {"calls": real, "by_model": by_model,
            "total_calls": len(real),
            "total_prompt_tokens": sum(c["prompt_tokens"] for c in real),
            "total_completion_tokens": sum(c["completion_tokens"] for c in real),
            "mock_calls": len(mock)}

if __name__ == "__main__":
    # CLI: python3 code/model_assist.py intent|media [backend] < input.txt
    #      python3 code/model_assist.py verify <output.csv> [backend] [limit]
    task = sys.argv[1] if len(sys.argv) > 1 else "intent"
    if task == "verify":
        backend = sys.argv[3] if len(sys.argv) > 3 else "none"
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
        vs = run_verification(sys.argv[2], backend, limit)
        print(f"{len(vs)} cases reviewed",
              "| inconsistent:", sum(1 for v in vs if v["verdict"] == "INCONSISTENT"))
    else:
        backend = sys.argv[2] if len(sys.argv) > 2 else "none"
        out = assist(task, sys.stdin.read(), backend=backend)
        print(out if out is not None else "SKIPPED: no active backend (deterministic run)")
