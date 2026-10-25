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
RES_RE = re.compile(r"\b(" + "|".join(PREFIXES) + r")(?:[_.\-]|[ \t]+)?(\d+)\b")

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
    same line as a resource mention attach unless an explicit raw-document
    panel supplies owner fields. That panel ends before activity history.
    Other documents do not inherit identifiers from neighboring lines.
    """
    records = {}
    mentions = list(RES_RE.finditer(text))
    distinct = {_canon(m) for m in mentions}
    single = len(distinct) <= 1
    lines = text.split("\n")
    # line index for each mention
    pos = 0
    line_starts = []
    for ln in lines:
        line_starts.append(pos)
        pos += len(ln) + 1
    import bisect
    detail_sections = {}
    stop_heading = re.compile(r"^\s*(?:Recent\s+)?(?:Activity(?: Log)?|History|Search history|Search results|Related(?: documents)?|Comments|Attachments|Summary)(?:\s*\(\d+\))?\s*:?\s*$", re.I)
    heading = re.compile(r"^\s*Raw document\s*[-:]\s*(.+)$", re.I)
    for i, line in enumerate(lines):
        match = heading.match(line)
        resources = list(RES_RE.finditer(match.group(1))) if match else []
        resource = resources[0] if len(resources) == 1 else None
        if not resource:
            for ambiguous in resources:
                detail_sections.setdefault(_canon(ambiguous), [])
            continue
        end = i + 1
        while end < len(lines) and not (heading.match(lines[end]) or stop_heading.match(lines[end])):
            end += 1
        detail_sections.setdefault(_canon(resource), []).append("\n".join(lines[i + 1:end]))
    request_sections = {}
    if source_ext == ".pdf":
        for i, line in enumerate(lines):
            if line.strip().lower() != "customer request":
                continue
            section = []
            for row in lines[i + 1:]:
                if "\f" in row or re.match(r"^\s*(?:Product|Order and delivery details|Attachment properties)\b", row, re.I):
                    break
                section.append(row)
            references = {_canon(m) for row in section if re.match(r"^\s*Detail\s+reference\b", row, re.I) for m in RES_RE.finditer(row)}
            if len(references) == 1:
                request_sections[next(iter(references))] = "\n".join(row for row in section if re.match(r"^\s*Detail\s+", row, re.I))
    history = False
    history_lines = set()
    for i, line in enumerate(lines):
        match = heading.match(line)
        if match and len(list(RES_RE.finditer(match.group(1)))) == 1:
            history = False
        elif stop_heading.match(line):
            history = True
        if history:
            history_lines.add(i)
    for m in mentions:
        rid = _canon(m)
        li = bisect.bisect_right(line_starts, m.start()) - 1
        seg = lines[li]
        state_seg = seg
        if rid in detail_sections:
            state_seg = "\n".join(detail_sections[rid])
            labeled = []
            for section in detail_sections[rid]:
                for line in section.splitlines():
                    field = re.fullmatch(r"\s*(e-?mail|customer[_ ]reference|user[_ ]id|phone|email_hash)\s*:?[ \t]+(.+?)\s*", line, re.I)
                    if not field:
                        continue
                    key, value = field.group(1).lower().replace(" ", "_").replace("e-mail", "email"), field.group(2)
                    pattern = EMAIL_RE if key == "email" else UID_RE if key in ("user_id", "customer_reference") else PHONE_RE if key == "phone" else HASH_RE
                    if pattern.fullmatch(value):
                        labeled.append((key, value))
            seg = "\n".join(value for key, value in labeled if len({v for k, v in labeled if k == key}) == 1)
        elif rid in request_sections:
            values = [re.sub(r"^\s*Detail\s+", "", row, flags=re.I).strip() for row in request_sections[rid].splitlines()]
            seg = "\n".join(value for value in values if EMAIL_RE.fullmatch(value) or UID_RE.fullmatch(value) or PHONE_RE.fullmatch(value) or HASH_RE.fullmatch(value))
        elif li in history_lines:
            seg = ""
            state_seg = ""
        if single and rid not in detail_sections:
            state_seg = text
        r = records.setdefault(rid, {
            "resource_id": rid, "system_id": system_for(rid),
            "category": "", "state": None,
            "emails": set(), "user_ids": set(), "phones": set(), "hashes": set()})
        if rid in detail_sections:
            detail_emails = {e.lower() for e in EMAIL_RE.findall(seg)}
            for other in mentions:
                other_li = bisect.bisect_right(line_starts, other.start()) - 1
                if _canon(other) != rid or other_li in history_lines or heading.match(lines[other_li]):
                    continue
                row_emails = {e.lower() for e in EMAIL_RE.findall(lines[other_li])}
                if row_emails and row_emails != detail_emails:
                    seg = ""
                    break
        r["emails"] |= {e.lower() for e in EMAIL_RE.findall(seg)}
        r["user_ids"] |= set(UID_RE.findall(seg))
        r["phones"] |= {p.strip() for p in PHONE_RE.findall(seg)}
        r["hashes"] |= set(HASH_RE.findall(seg))
        st = guess_state(rid, state_seg, text)
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
            table = any(re.search(r"\bsender\b", line, re.I) and
                        re.search(r"\b(message|messages|lessage|content|text)\b", line, re.I) and
                        (re.search(r"\b(time|date)\b", line, re.I) and i + 1 < len(lines) and lines[i + 1].strip()
                         or sum(bool(re.search(r"\b[0-2]?\d:[0-5]\d\b", row)) for row in lines[i + 1:i + 9]) >= 2)
                        for i, line in enumerate(lines))
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
