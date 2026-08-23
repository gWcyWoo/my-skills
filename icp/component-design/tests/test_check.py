import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check.py"


def run(*argv, expect=0):
    p = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True)
    out = json.loads(p.stdout.strip()) if p.stdout.strip() else {}
    if expect is not None:
        assert p.returncode == expect, f"{argv}\nrc={p.returncode}\n{p.stdout}\n{p.stderr}"
    return p.returncode, out


GOOD_CHECKLIST = """\
# Stage 2 Checklist

## Step 1: 识别平台 + 扫描组件
- [x] platform: flutter/material
- [x] scanned_dirs: lib/widgets, lib/shared
- [x] shared_components: 3 个 (AppNavBar, AppButton, AppCard)

## Step 2: 组件匹配
- [x] groups_bound: 4 groups → 4 components
- [x] new_reuse_scan: LoginForm 扫描 lib/widgets lib/shared 无匹配
- [x] extract_shared_scan: 5 组两两比对，OtpInput 抽取为公共
- [x] affected_complete: OtpInput affected 2 个 (PageAOtp, PageBOtp)
- [x] check_binding: 通过，2 轮修正

## Step 3: 交互拆解
- [x] apis_parsed: 3 apis
- [x] interactions_decomposed: 8 个交互
- [x] coverage_verified: 12 句全覆盖
- [x] flow_traced: 3 条路径，无断链
- [x] fields_verified: 8 个交互字段核对通过
- [x] check_interactions: 通过，1 轮修正
"""


class TestCheckAll(unittest.TestCase):

    def test_all_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(GOOD_CHECKLIST, encoding="utf-8")
            _, out = run(str(p))
            self.assertTrue(out["ok"])

    def test_unchecked_item(self):
        cl = GOOD_CHECKLIST.replace("[x] platform:", "[ ] platform:")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(cl, encoding="utf-8")
            _, out = run(str(p), expect=1)
            self.assertFalse(out["ok"])
            self.assertEqual(out["errors"][0]["type"], "unchecked")
            self.assertEqual(out["errors"][0]["key"], "platform")
            self.assertEqual(out["errors"][0]["step"], 1)

    def test_empty_value(self):
        cl = GOOD_CHECKLIST.replace(
            "[x] platform: flutter/material",
            "[x] platform: ",
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(cl, encoding="utf-8")
            _, out = run(str(p), expect=1)
            self.assertFalse(out["ok"])
            self.assertEqual(out["errors"][0]["type"], "empty_value")
            self.assertEqual(out["errors"][0]["key"], "platform")

    def test_multiple_errors(self):
        cl = GOOD_CHECKLIST.replace("[x] platform:", "[ ] platform:").replace(
            "[x] apis_parsed:", "[ ] apis_parsed:"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(cl, encoding="utf-8")
            _, out = run(str(p), expect=1)
            self.assertFalse(out["ok"])
            self.assertEqual(len(out["errors"]), 2)
            keys = {e["key"] for e in out["errors"]}
            self.assertEqual(keys, {"platform", "apis_parsed"})

    def test_empty_checklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text("# nothing here\n", encoding="utf-8")
            _, out = run(str(p), expect=1)
            self.assertEqual(out["errors"][0]["type"], "empty_checklist")


class TestCheckStep(unittest.TestCase):

    def test_step_1_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(GOOD_CHECKLIST, encoding="utf-8")
            _, out = run(str(p), "--step", "1")
            self.assertTrue(out["ok"])

    def test_step_filter_ignores_other_steps(self):
        cl = GOOD_CHECKLIST.replace("[x] apis_parsed:", "[ ] apis_parsed:")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(cl, encoding="utf-8")
            _, out = run(str(p), "--step", "1")
            self.assertTrue(out["ok"])

    def test_step_filter_catches_own_step(self):
        cl = GOOD_CHECKLIST.replace("[x] apis_parsed:", "[ ] apis_parsed:")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(cl, encoding="utf-8")
            _, out = run(str(p), "--step", "3", expect=1)
            self.assertFalse(out["ok"])
            self.assertEqual(out["errors"][0]["key"], "apis_parsed")

    def test_unknown_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(GOOD_CHECKLIST, encoding="utf-8")
            _, out = run(str(p), "--step", "9", expect=1)
            self.assertEqual(out["errors"][0]["type"], "unknown_step")

    def test_uppercase_x(self):
        cl = GOOD_CHECKLIST.replace("[x] platform:", "[X] platform:")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "checklist.md"
            p.write_text(cl, encoding="utf-8")
            _, out = run(str(p), "--step", "1")
            self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
