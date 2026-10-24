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

def assist(task, text, backend="none", model=MODEL):
    """Return the model's answer text, or None when no backend is active."""
    if backend == "none":
        return None
    if backend == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        prompt = (INTENT_PROMPT if task == "intent" else MEDIA_PROMPT).format(text=text)
        answer, pt, ct = _gemini(prompt, key, model)
        log_call(task, backend, model, pt, ct)
        return answer
    raise ValueError(f"unknown backend: {backend}")

def summarize_usage(log_path=USAGE_LOG):
    """Aggregate the measured usage log for evaluation/usage_report.md."""
    calls = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            calls = [json.loads(l) for l in f if l.strip()]
    by_model = {}
    for c in calls:
        m = by_model.setdefault(c["model"], {"calls": 0, "prompt_tokens": 0,
                                             "completion_tokens": 0})
        m["calls"] += 1
        m["prompt_tokens"] += c["prompt_tokens"]
        m["completion_tokens"] += c["completion_tokens"]
    return {"calls": calls, "by_model": by_model,
            "total_calls": len(calls),
            "total_prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "total_completion_tokens": sum(c["completion_tokens"] for c in calls)}

if __name__ == "__main__":
    # CLI: python3 code/model_assist.py intent|media [backend] < input.txt
    task = sys.argv[1] if len(sys.argv) > 1 else "intent"
    backend = sys.argv[2] if len(sys.argv) > 2 else "none"
    out = assist(task, sys.stdin.read(), backend=backend)
    print(out if out is not None else "SKIPPED: no active backend (deterministic run)")
