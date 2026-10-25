"""Offline checks for separate explicit vision extraction."""
import hashlib, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import vision_evidence as v


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "image.png").write_bytes(b"synthetic png bytes")
        self.base = {"file_id":"evidence_1","model":"gemini-3.5-flash-lite","source_sha256":hashlib.sha256(b"synthetic png bytes").hexdigest(),
                     "prompt_sha256":hashlib.sha256(pathlib.Path(v.__file__).with_name("vision_prompt.txt").read_bytes()).hexdigest(),
                     "reviewed":True,"records":[{"resource_id":"data_flow_1","emails":["alice@example.com"],"user_ids":[],"state":"ACTIVE"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_extraction_requires_key(self):
        (self.root/"evidence_files.csv").write_text("file_id,file_path,origin,captured_at\nevidence_1,image.png,test,2026-01-01T00:00:00Z\n")
        with patch.dict(os.environ,{"GEMINI_API_KEY":""}),self.assertRaises(ValueError):v.extract_image(str(self.root),"evidence_1",str(self.root/"out"))

    def test_explicit_call_is_bounded_and_unreviewed(self):
        import io, urllib.request
        (self.root/"evidence_files.csv").write_text("file_id,file_path,origin,captured_at\nevidence_1,image.png,test,2026-01-01T00:00:00Z\n")
        payload={"candidates":[{"content":{"parts":[{"text":json.dumps({"records":self.base["records"]})}]}}],"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":5}}
        with patch.dict(os.environ,{"GEMINI_API_KEY":"synthetic-not-secret"}),patch.object(urllib.request,"urlopen",return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            path=v.extract_image(str(self.root),"evidence_1",str(self.root/"out"))
        self.assertEqual(call.call_count,1)
        request=call.call_args.args[0]
        body=json.loads(request.data)
        self.assertEqual(body["generationConfig"]["maxOutputTokens"],2048)
        self.assertEqual(call.call_args.kwargs["timeout"],90)
        result=json.loads(pathlib.Path(path).read_text())
        self.assertIs(result["reviewed"],False)
        self.assertEqual(result["usage"],payload["usageMetadata"])
        self.assertNotIn("synthetic-not-secret",pathlib.Path(path).read_text())

    def test_failed_call_has_no_retry_or_cache(self):
        import urllib.request, urllib.error
        (self.root/"evidence_files.csv").write_text("file_id,file_path,origin,captured_at\nevidence_1,image.png,test,2026-01-01T00:00:00Z\n")
        with patch.dict(os.environ,{"GEMINI_API_KEY":"synthetic-not-secret"}),patch.object(urllib.request,"urlopen",side_effect=urllib.error.URLError("offline")) as call:
            with self.assertRaises(urllib.error.URLError):v.extract_image(str(self.root),"evidence_1",str(self.root/"out"))
        self.assertEqual(call.call_count,1)
        self.assertFalse((self.root/"out").exists())

    def test_existing_cache_never_triggers_paid_retry_or_overwrite(self):
        import urllib.request
        (self.root/"evidence_files.csv").write_text("file_id,file_path,origin,captured_at\nevidence_1,image.png,test,2026-01-01T00:00:00Z\n")
        (self.root/"evidence_1.json").write_text("reviewed original")
        original=(self.root/"evidence_1.json").read_bytes()
        with patch.object(urllib.request,"urlopen",side_effect=AssertionError("network not allowed")),self.assertRaises(ValueError):
            v.extract_image(str(self.root),"evidence_1",str(self.root))
        self.assertEqual((self.root/"evidence_1.json").read_bytes(),original)

    def test_incomplete_response_is_not_saved(self):
        import io, urllib.request
        (self.root/"evidence_files.csv").write_text("file_id,file_path,origin,captured_at\nevidence_1,image.png,test,2026-01-01T00:00:00Z\n")
        for text in ("[]", "{}", "not json"):
            payload={"candidates":[{"content":{"parts":[{"text":text}]}}]}
            with self.subTest(text=text),patch.dict(os.environ,{"GEMINI_API_KEY":"synthetic-not-secret"}),patch.object(urllib.request,"urlopen",return_value=io.BytesIO(json.dumps(payload).encode())),self.assertRaises(ValueError):
                v.extract_image(str(self.root),"evidence_1",str(self.root/"out"))
            self.assertFalse((self.root/"out").exists())

    def test_source_cannot_escape_dataset(self):
        import urllib.request
        (self.root/"evidence_files.csv").write_text("file_id,file_path,origin,captured_at\nevidence_1,../private.png,test,2026-01-01T00:00:00Z\n")
        with patch.object(urllib.request,"urlopen",side_effect=AssertionError("network not allowed")),self.assertRaises(ValueError):
            v.extract_image(str(self.root),"evidence_1",str(self.root/"out"))


if __name__ == "__main__":unittest.main()
