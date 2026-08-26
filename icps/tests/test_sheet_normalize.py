import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sheet_normalize.py"

# Verbatim header row of the production sheet. Note the role columns are NOT
# contiguous (status/pr/reviews for both roles, then last_error/lease_* for
# both) — position-based mapping would silently mis-assign them.
HEADER = ["标题", "Route", "设计稿地址", "UI补充描述", "交互描述", "UT", "IT", "E2E",
          "接口描述", "PRN ID",
          "frontend status", "frontend pr", "frontend reviews",
          "backend status", "backend pr", "backend reviews",
          "frontend last_error", "frontend lease_token", "frontend lease_until",
          "backend last_error", "backend lease_token", "backend lease_until"]


def row(**kw):
    """Build a positional sheet row from canonical field names."""
    pos = {"标题": "title", "Route": "route", "设计稿地址": "design", "UI补充描述": "ui",
           "交互描述": "ix", "UT": "ut", "IT": "it", "E2E": "e2e", "接口描述": "api",
           "PRN ID": "prn", "frontend status": "fstatus", "frontend pr": "fpr",
           "frontend reviews": "freviews", "backend status": "bstatus",
           "backend pr": "bpr", "backend reviews": "breviews",
           "frontend last_error": "ferror", "frontend lease_token": "ftoken",
           "frontend lease_until": "funtil", "backend last_error": "berror",
           "backend lease_token": "btoken", "backend lease_until": "buntil"}
    return [kw.get(pos[h], "") for h in HEADER]


def run(values, expect=0):
    tmp = Path(tempfile.mkdtemp())
    src, out = tmp / "raw.json", tmp / "sheet.json"
    src.write_text(json.dumps({"result": {"valueRanges": [{"values": values}]}},
                              ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--values", str(src), "--out", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == expect, f"rc={p.returncode}\n{p.stdout}\n{p.stderr}"
    summary = json.loads(p.stdout.strip().splitlines()[-1])
    backend = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return summary, backend


def run_raw(doc, expect=0):
    """Feed an arbitrary raw document (e.g. an API error envelope) to the script."""
    tmp = Path(tempfile.mkdtemp())
    src, out = tmp / "raw.json", tmp / "sheet.json"
    src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--values", str(src), "--out", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == expect, f"rc={p.returncode}\n{p.stdout}\n{p.stderr}"
    return json.loads(p.stdout.strip().splitlines()[-1])


class TestSheetNormalize(unittest.TestCase):

    def test_non_contiguous_role_columns_map_by_name(self):
        _, backend = run([HEADER, row(title="登录", route="signin", fstatus="ready",
                                      fpr="mr/1", bstatus="review", bpr="mr/2",
                                      ftoken="tok-f", btoken="tok-b")])
        r = backend["rows"][0]
        self.assertEqual(r["roles"]["frontend"]["status"], "ready")
        self.assertEqual(r["roles"]["frontend"]["pr"], "mr/1")
        self.assertEqual(r["roles"]["frontend"]["lease_token"], "tok-f")
        self.assertEqual(r["roles"]["backend"]["status"], "review")
        self.assertEqual(r["roles"]["backend"]["pr"], "mr/2")
        self.assertEqual(r["roles"]["backend"]["lease_token"], "tok-b")

    def test_row_id_is_sheet_row_number(self):
        _, backend = run([HEADER, row(title="A"), row(title="B"), row(title="C")])
        self.assertEqual([r["row_id"] for r in backend["rows"]], ["r2", "r3", "r4"])

    def test_blank_title_rows_skipped(self):
        _, backend = run([HEADER, row(title="A"), [], row(), ["", "", "", "", "", "  "],
                          row(title="B")])
        self.assertEqual([r["title"] for r in backend["rows"]], ["A", "B"])

    def test_design_urls_multiline_and_prose_dropped(self):
        two = ("https://lanhuapp.com/web/#/item/project/detailDetach?image_id=be0332b9\n"
               "https://lanhuapp.com/web/#/item/project/detailDetach?image_id=d5e12f83")
        _, backend = run([HEADER, row(title="权限声明", design=two),
                          row(title="公共组件--Card", design="无")])
        self.assertEqual(len(backend["rows"][0]["payload"]["design_urls"]), 2)
        self.assertEqual(backend["rows"][1]["payload"]["design_urls"], [])

    def test_route_whitespace_stripped(self):
        # The 反馈 row's Route cell really is "\nfeedback".
        _, backend = run([HEADER, row(title="反馈", route="\nfeedback")])
        self.assertEqual(backend["rows"][0]["payload"]["route"], "feedback")

    def test_empty_role_cell_becomes_null_not_empty_string(self):
        _, backend = run([HEADER, row(title="A")])
        self.assertIsNone(backend["rows"][0]["roles"]["frontend"]["status"])

    def test_missing_column_halts(self):
        bad = [h for h in HEADER if h != "交互描述"]
        summary, backend = run([bad, [""] * len(bad)], expect=1)
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["errors"][0]["code"], "missing_column")
        self.assertEqual(summary["errors"][0]["where"], "interaction_description")
        self.assertIsNone(backend)

    def test_duplicate_title_halts(self):
        # Titles are the key interactions resolve against; duplicates are ambiguous.
        summary, _ = run([HEADER, row(title="登录"), row(title="登录")], expect=1)
        self.assertEqual(summary["errors"][0]["code"], "duplicate_title")

    def test_api_error_envelope_404_reports_doc_not_found(self):
        """MCP/API 返回 404 信封时，必须直呼 doc_not_found，而不是含糊的 no_values。"""
        summary = run_raw({"error": {"code": 404,
                                     "message": "Requested entity was not found.",
                                     "status": "NOT_FOUND"}}, expect=1)
        self.assertEqual(summary["errors"][0]["code"], "doc_not_found")

    def test_api_error_envelope_other_code_reports_source_error(self):
        """非 404 的错误信封归 source_error，并带上原始 code 供定位。"""
        summary = run_raw({"error": {"code": 403, "message": "denied",
                                     "status": "PERMISSION_DENIED"}}, expect=1)
        self.assertEqual(summary["errors"][0]["code"], "source_error")
        self.assertEqual(summary["errors"][0]["detail"]["code"], 403)

    def test_codex_structured_content_envelope(self):
        doc = {"structuredContent": {"result": {"values": [HEADER, row(title="A")]}}}
        tmp = Path(tempfile.mkdtemp())
        src, out = tmp / "raw.json", tmp / "sheet.json"
        src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "--values", str(src),
                            "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads(out.read_text())["rows"][0]["title"], "A")

    def test_codex_error_content_404_reports_doc_not_found(self):
        summary = run_raw({"content": [{"type": "text", "text":
                           "Error executing tool get_sheet_data: HttpError 404"}],
                           "isError": True}, expect=1)
        self.assertEqual(summary["errors"][0]["code"], "doc_not_found")

    def test_codex_text_content_can_hold_bare_values_array(self):
        doc = {"content": [{"type": "text", "text":
               json.dumps([HEADER, row(title="A")], ensure_ascii=False)}]}
        tmp = Path(tempfile.mkdtemp())
        src, out = tmp / "raw.json", tmp / "sheet.json"
        src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "--values", str(src),
                            "--out", str(out)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads(out.read_text())["rows"][0]["title"], "A")


if __name__ == "__main__":
    unittest.main()
