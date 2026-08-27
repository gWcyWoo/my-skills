"""Tests for validate.py — string extraction + absolute positioning detection."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate import _extract_string_literals, cmd_check_codegen


class TestExtractStringLiterals(unittest.TestCase):

    def test_normal_strings_extracted(self):
        source = 'val a = "hello"\nval b = "world"'
        literals = _extract_string_literals(source)
        self.assertIn("hello", literals)
        self.assertIn("world", literals)

    def test_raw_string_does_not_poison_subsequent_literals(self):
        """Triple-quoted raw string with odd embedded quotes desyncs the regex."""
        source = 'val x = """hello "world"""\nval y = "target text"'
        literals = _extract_string_literals(source)
        self.assertIn("target text", literals)


class TestAbsolutePositioning(unittest.TestCase):

    def _run_check(self, kt_source, filename="Screen.kt"):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            bp = td / "bp.json"
            bp.write_text(json.dumps({"components": []}))
            ct = td / "ct.json"
            ct.write_text(json.dumps({"apis": []}))
            gen = td / "gen"
            gen.mkdir()
            (gen / filename).write_text(kt_source)

            args = argparse.Namespace(
                blueprint=str(bp), contract=str(ct),
                gen_dir=str(gen), platform="compose",
            )
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    cmd_check_codegen(args)
            except SystemExit:
                pass
            return json.loads(buf.getvalue())

    def test_offset_detected(self):
        result = self._run_check(
            'val m = Modifier.offset(x = 16.dp, y = 104.dp)\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["count"], 1)
        self.assertIn("Screen.kt:1", errs[0]["sites"])

    def test_deep_wrapped_proportional_allowed(self):
        result = self._run_check(
            'val m = Modifier.offset(\n    x = 16.dp,\n    y = maxHeight * 0.3f,\n)\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)

    def test_no_offset_clean(self):
        result = self._run_check(
            'Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {}\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)

    def test_absolute_offset_detected(self):
        result = self._run_check(
            'val m = Modifier.absoluteOffset(x = 20.dp, y = 30.dp)\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)

    def test_trailing_lambda_offset_detected(self):
        result = self._run_check(
            'val m = Modifier.offset { IntOffset(16, 104) }\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)

    def test_proportional_maxwidth_only(self):
        result = self._run_check(
            'val m = Modifier.offset(x = maxWidth * 0.1f)\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)

    def test_comment_only_not_flagged(self):
        result = self._run_check(
            '// val m = Modifier.offset(x = 16.dp)\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)

    def test_string_literal_not_flagged(self):
        result = self._run_check(
            'val s = "use Modifier.offset(x) sparingly"\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)

    def test_comment_keyword_does_not_exempt(self):
        result = self._run_check(
            'val m = Modifier.offset(x = 16.dp) // maxHeight ok\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)

    def test_block_comment_not_flagged(self):
        result = self._run_check(
            '/* val m = Modifier.offset(x = 16.dp) */\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)

    def test_block_comment_keyword_does_not_exempt(self):
        result = self._run_check(
            'val m = Modifier.offset(x = 16.dp) /* maxHeight */\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)

    def test_block_comment_splice_does_not_forge_keyword(self):
        result = self._run_check(
            'val m = Modifier.offset(x = max/*c*/Width * 0.5f)\n'
        )
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)


if __name__ == "__main__":
    unittest.main()
