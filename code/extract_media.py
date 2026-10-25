"""Generic media-evidence extractor.

Regenerates code/extracted/<file_id>.json sidecars from the actual PNG/PDF
evidence files (OCR via tesseract, text layer via pdftotext). Sidecars carry
the source file_id so the audit engine cites the original evidence, never the
extraction cache. No corpus facts are baked in: everything below is parsed
from the extracted text at run time.
"""
import csv, hashlib, json, os, re, subprocess, sys

PREFIXES = ("account", "tombstone", "search", "cache", "support", "analytics",
            "telemetry", "data_flow", "backup", "audit_record", "export",
            "marketing", "object", "legal_hold", "email_log", "secondary")
# OCR sometimes drops or substitutes the underscore before the digits
RES_RE = re.compile(r"\b(" + "|".join(PREFIXES) + r")[_.\-]?(\d+)\b")

def _canon(m):
    return f"{m.group(1)}_{m.group(2)}"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
UID_RE = re.compile(r"\buser_\d+\b")
PHONE_RE = re.compile(r"\+\d[\d ()-]{6,}\d")
HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")

PREFIX_SYSTEM = [("account_", "account_service"), ("tombstone_", "identity_service"),
    ("search_", "search_service"), ("cache_", "cache_service"),
    ("support_", "support_platform"), ("analytics_", "analytics_platform"),
    ("telemetry_", "telemetry_platform"), ("data_flow_", "integration_service"),
    ("backup_", "backup_service"), ("audit_record_", "security_service"),
    ("export_", "export_service"), ("marketing_", "marketing_service"),
    ("object_", "support_platform"), ("legal_hold_", "legal_service"),
    ("email_log_", "notification_service"), ("secondary_", "account_service")]
SYSTEM_CATEGORY = {
    "account_service": "USER_PROFILE", "identity_service": "ACCOUNT_TOMBSTONE",
    "search_service": "SEARCH_INDEX_ENTRY", "cache_service": "CACHE_ENTRY",
    "support_platform": "SUPPORT_MESSAGE", "analytics_platform": "ANALYTICS_PROFILE",
    "telemetry_platform": "PRODUCT_TELEMETRY", "integration_service": "DATA_FLOW",
    "backup_service": "BACKUP_ARCHIVE", "security_service": "SECURITY_AUDIT_LOG",
    "export_service": "USER_EXPORT", "marketing_service": "MARKETING_PROFILE",
    "notification_service": "EMAIL_DELIVERY_LOG", "legal_service": "LEGAL_HOLD_RECORD"}

def system_for(rid):
    for p, s in PREFIX_SYSTEM:
        if rid.startswith(p):
            return s
    return ""

def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            return subprocess.run(["pdftotext", "-layout", path, "-"],
                                  capture_output=True, text=True, timeout=60, check=True).stdout
        if ext == ".png":
            return subprocess.run(["tesseract", path, "-"],
                                  capture_output=True, text=True, timeout=120, check=True).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Cannot extract evidence {os.path.basename(path)}: install tesseract-ocr and poppler-utils and check the source file") from exc
    return ""

def guess_state(rid, seg, whole):
    """State from the document's own words around the resource mention."""
    s = seg.lower()
    if "404" in s or "not found" in s or "no longer exists" in s or "deleted" in s:
        return "ABSENT"
    if "[redacted]" in s:
        return "CLEAN"
    if "anonymized" in s or "anonymised" in s:
        return "ANONYMIZED"
    if rid.startswith("data_flow_"):
        if "disabled" in s or "enabled=false" in s.replace(" ", ""):
            return "DISABLED"
        return "ACTIVE"
    if rid.startswith("backup_"):
        if "restore_allowed=false" in s.replace(" ", "") or "blocked" in s:
            return "BLOCKED"
        return "ACTIVE"
    if rid.startswith("audit_record_") or rid.startswith("legal_hold_"):
        return "RETAINED"
    return "PRESENT"

def parse_records(text, source_ext=""):
    """One record per resource mention.

    Identity association policy (false-binding guard): identifiers on the
    same line as a resource mention always attach. Identifiers from the
    surrounding blank-line-delimited block attach only when the document
    mentions a single resource - consoles listing several resources put
    owner columns on separate lines, and block-level sweeps mis-bind them.
    """
    records = {}
    mentions = list(RES_RE.finditer(text))
    distinct = {_canon(m) for m in mentions}
    # A document about a single resource: every identifier in it belongs to
    # that resource (label/value layouts scatter them across blocks).
    single = len(distinct) <= 1
    lines = text.splitlines()
    # line index for each mention
    pos = 0
    line_starts = []
    for ln in lines:
        line_starts.append(pos)
        pos += len(ln) + 1
    import bisect
    def block_of(li):
        lo = li
        while lo > 0 and lines[lo - 1].strip():
            lo -= 1
        hi = li
        while hi + 1 < len(lines) and lines[hi + 1].strip():
            hi += 1
        return "\n".join(lines[lo:hi + 1])
    for m in mentions:
        rid = _canon(m)
        li = bisect.bisect_right(line_starts, m.start()) - 1
        seg = lines[li]
        if single:
            seg = text
        r = records.setdefault(rid, {
            "resource_id": rid, "system_id": system_for(rid),
            "category": "", "state": None,
            "emails": set(), "user_ids": set(), "phones": set(), "hashes": set()})
        r["emails"] |= {e.lower() for e in EMAIL_RE.findall(seg)}
        r["user_ids"] |= set(UID_RE.findall(seg))
        r["phones"] |= {p.strip() for p in PHONE_RE.findall(seg)}
        r["hashes"] |= set(HASH_RE.findall(seg))
        st = guess_state(rid, seg, text)
        if r["state"] in (None, "PRESENT") or st != "PRESENT":
            r["state"] = st
    out = []
    is_pdf = source_ext == ".pdf"
    for r in records.values():
        r["category"] = SYSTEM_CATEGORY.get(r["system_id"], "UNKNOWN")
        if r["resource_id"].startswith("object_"):
            r["category"] = "SUPPORT_ATTACHMENT"
        elif r["resource_id"].startswith("support_"):
            support_ids = {rid for rid in distinct if rid.startswith("support_")}
            table = any(re.search(r"\b(time|date)\b", line, re.I) and re.search(r"\bsender\b", line, re.I) and
                        re.search(r"\b(message|messages|lessage|content|text)\b", line, re.I) and
                        i + 1 < len(lines) and lines[i + 1].strip() for i, line in enumerate(lines))
            attachment = is_pdf and re.search(r"\battachment properties\b", text, re.I) and re.search(r"\b(upload|uploader|file)\b", text, re.I)
            if len(support_ids) != 1 or table and attachment:
                r["state"] = "BIND"
            elif table:
                r["category"] = "SUPPORT_MESSAGE"
            elif attachment:
                r["category"] = "SUPPORT_ATTACHMENT"
            else:
                r["state"] = "BIND"
        if r["state"] is None:
            r["state"] = "PRESENT"
        for k in ("emails", "user_ids", "phones", "hashes"):
            r[k] = sorted(r[k])
        out.append(r)
    return out

def main(ds, outdir):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(ds, "evidence_files.csv")) as f:
        rows = list(csv.DictReader(f))
    n = 0
    for row in rows:
        path = row["file_path"]
        if os.path.splitext(path)[1].lower() not in (".png", ".pdf"):
            continue
        full = os.path.join(ds, path)
        text = extract_text(full)
        if not text.strip():
            raise RuntimeError(f"Empty media extraction for {path}; refusing to silently omit evidence")
        recs = parse_records(text, os.path.splitext(path)[1].lower())
        for r in recs:
            r["observed_at"] = row["captured_at"]
        with open(os.path.join(outdir, row["file_id"] + ".json"), "w") as g:
            json.dump({"file_id": row["file_id"], "file_path": path,
                       "captured_at": row["captured_at"],
                       "extractor": "pdftotext/tesseract",
                       "text": text,
                       "source_sha256": hashlib.sha256(open(full, "rb").read()).hexdigest(),
                       "records": recs}, g, indent=2)
        n += 1
        print(f"{row['file_id']}: {len(recs)} resources from {os.path.basename(path)}")
    print(f"extracted {n} media files")

if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "dataset"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "extracted")
    main(ds, out)
