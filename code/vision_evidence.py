"""One explicitly selected model image extraction, separate from predictions."""
import hashlib, json, os, re
from pathlib import Path


def extract_image(ds, file_id, outdir):
    """One explicit API call for one selected image; output needs visual review."""
    import base64, csv, urllib.request
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise ValueError("Invalid vision evidence file ID")
    with open(os.path.join(ds, "evidence_files.csv")) as f:
        manifest = {r["file_id"]:r for r in csv.DictReader(f)}
    meta = manifest[file_id]
    root = Path(ds).resolve()
    selected = (root / meta["file_path"]).resolve()
    if not selected.is_relative_to(root):
        raise ValueError("Vision source must stay inside the selected dataset")
    path = str(selected)
    if os.path.splitext(path)[1].lower() != ".png":
        raise ValueError("Vision extraction currently supports PNG only")
    if os.path.getsize(path) > 5_000_000:
        raise ValueError("Vision image exceeds 5 MB cap")
    destination = os.path.join(outdir,file_id+".json")
    if os.path.exists(destination):
        raise ValueError("Vision extraction cache already exists; choose a new directory")
    raw = Path(path).read_bytes()
    if len(raw) > 5_000_000:
        raise ValueError("Vision image exceeds 5 MB cap")
    prompt = Path(__file__).with_name("vision_prompt.txt").read_text()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is required for explicit extraction")
    body = {"contents":[{"parts":[{"text":prompt},{"inline_data":{"mime_type":"image/png","data":base64.b64encode(raw).decode()}}]}],
            "generationConfig":{"temperature":0,"maxOutputTokens":2048,"responseMimeType":"application/json"}}
    request = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent",
                                    data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":key})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw_response = response.read(100_001)
    if len(raw_response) > 100_000:
        raise ValueError("Vision response exceeds 100 KB cap")
    data = json.loads(raw_response)
    candidates = data.get("candidates", [])
    if len(candidates) != 1 or candidates[0].get("finishReason", "STOP") != "STOP":
        raise ValueError("Vision response must have one complete candidate")
    text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
    decoded = json.loads(text)
    if not isinstance(decoded, dict) or not isinstance(decoded.get("records"), list):
        raise ValueError("Vision response does not contain a records list")
    result = {"file_id":file_id,"model":"gemini-3.5-flash-lite","source_sha256":hashlib.sha256(raw).hexdigest(),
              "prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"records":decoded["records"],
              "usage":data.get("usageMetadata",{}),"reviewed":False,"source_file_path":meta["file_path"],"response_model":data.get("modelVersion"),"finish_reason":data.get("candidates", [{}])[0].get("finishReason")}
    os.makedirs(outdir,exist_ok=True)
    with open(destination,"x") as f:
        json.dump(result,f,indent=2)
    return destination


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        raise SystemExit("Usage: python3 code/vision_evidence.py DATASET FILE_ID OUTPUT_DIR; one API call, review required")
    print(extract_image(*sys.argv[1:]))
