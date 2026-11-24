"""Tests for validate.py — string extraction + absolute positioning detection."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
import subprocess
import unicodedata
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


    def test_triple_quoted_content_extracted(self):
        """Text inside triple-quoted raw strings must be extractable."""
        source = 'val terms = """\n用户协议内容\n"""'
        literals = _extract_string_literals(source)
        found = any("用户协议内容" in s for s in literals)
        self.assertTrue(found, f"raw string content not found in {literals}")

    def test_dart_single_quote_with_embedded_double(self):
        """Dart single-quoted string containing double quotes must not shred."""
        source = "final a = '他说\"你好\"了';"
        literals = _extract_string_literals(source, platform="flutter")
        self.assertIn('他说"你好"了', literals)
        self.assertNotIn('他说了', literals)

    def test_dart_triple_single_quoted_extracted(self):
        source = "final s = '''多行\n内容''';"
        literals = _extract_string_literals(source, platform="flutter")
        found = any("多行" in s for s in literals)
        self.assertTrue(found)


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


class TestFlutterPositioning(unittest.TestCase):

    def _run_flutter(self, dart_source):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            bp = td / "bp.json"
            bp.write_text(json.dumps({"components": []}))
            ct = td / "ct.json"
            ct.write_text(json.dumps({"apis": []}))
            gen = td / "gen"
            gen.mkdir()
            (gen / "screen.dart").write_text(dart_source)
            args = argparse.Namespace(
                blueprint=str(bp), contract=str(ct),
                gen_dir=str(gen), platform="flutter",
            )
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    cmd_check_codegen(args)
            except SystemExit:
                pass
            return json.loads(buf.getvalue())

    def test_positioned_near_mediaquery_still_flagged(self):
        """MediaQuery for keyboard insets must not exempt hardcoded Positioned."""
        src = (
            "Widget build(BuildContext context) {\n"
            "  final pad = MediaQuery.of(context).padding.top;\n"
            "  return Stack(children: [\n"
            "    Positioned(left: 12, top: 40, child: Text('x')),\n"
            "  ]);\n"
            "}\n"
        )
        result = self._run_flutter(src)
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 1)

    def test_positioned_with_constraints_exempted(self):
        """constraints.maxWidth on the offset line exempts proportional Positioned."""
        src = (
            "Widget build(BuildContext context) {\n"
            "  return Stack(children: [\n"
            "    Positioned(left: constraints.maxWidth * 0.1, child: Text('x')),\n"
            "  ]);\n"
            "}\n"
        )
        result = self._run_flutter(src)
        errs = [e for e in result["errors"] if e["type"] == "absolute_positioning"]
        self.assertEqual(len(errs), 0)


class TestAssetCoverage(unittest.TestCase):

    def _run_check(self, kt_source, blueprint_components, filename="Screen.kt"):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            bp = td / "bp.json"
            bp.write_text(json.dumps({"components": blueprint_components}))
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

    def test_asset_ref_missing(self):
        comps = [{"name": "nav", "assets": [
            {"id": "1", "name": "icon/back", "file": "assets/a.png",
             "resource_name": "icon_back", "size": {"width": 32, "height": 32}}
        ]}]
        result = self._run_check("val x = 1\n", comps)
        errs = [e for e in result["errors"] if e["type"] == "missing_asset_ref"]
        self.assertEqual(len(errs), 1)
        self.assertIn("icon_back", errs[0]["missing"])

    def test_asset_ref_present(self):
        comps = [{"name": "nav", "assets": [
            {"id": "1", "name": "icon/back", "file": "assets/a.png",
             "resource_name": "icon_back", "size": {"width": 32, "height": 32}}
        ]}]
        result = self._run_check(
            'val img = painterResource(R.drawable.icon_back)\n', comps)
        errs = [e for e in result["errors"] if e["type"] == "missing_asset_ref"]
        self.assertEqual(len(errs), 0)

    def test_asset_without_file_not_checked(self):
        comps = [{"name": "nav", "assets": [
            {"id": "1", "name": "icon/back",
             "resource_name": "icon_back", "size": {"width": 32, "height": 32}}
        ]}]
        result = self._run_check("val x = 1\n", comps)
        errs = [e for e in result["errors"] if e["type"] == "missing_asset_ref"]
        self.assertEqual(len(errs), 0)

    def test_multiple_assets_partial_coverage(self):
        comps = [{"name": "nav", "assets": [
            {"id": "1", "name": "icon/back", "file": "assets/a.png",
             "resource_name": "icon_back", "size": {"width": 32, "height": 32}},
            {"id": "2", "name": "icon/close", "file": "assets/b.png",
             "resource_name": "icon_close", "size": {"width": 24, "height": 24}},
        ]}]
        result = self._run_check(
            'val img = painterResource(R.drawable.icon_back)\n', comps)
        errs = [e for e in result["errors"] if e["type"] == "missing_asset_ref"]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["missing_count"], 1)
        self.assertIn("icon_close", errs[0]["missing"])
        self.assertNotIn("icon_back", errs[0]["missing"])

    def test_asset_substring_not_false_pass(self):
        """resource_name 'line' must not match 'lineHeight'."""
        comps = [{"name": "nav", "assets": [
            {"id": "1", "name": "line", "file": "assets/line.png",
             "resource_name": "line", "size": {"width": 2, "height": 40}}
        ]}]
        result = self._run_check(
            'Text(style = TextStyle(lineHeight = 20.sp))\n', comps)
        errs = [e for e in result["errors"] if e["type"] == "missing_asset_ref"]
        self.assertEqual(len(errs), 1)


class TestTextCoverageMultiSpan(unittest.TestCase):

    def _run_check(self, dart_source, blueprint_texts):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            bp = td / "bp.json"
            bp.write_text(json.dumps({"components": [
                {"name": "terms", "texts": [{"value": t} for t in blueprint_texts]}
            ]}))
            ct = td / "ct.json"
            ct.write_text(json.dumps({"apis": []}))
            gen = td / "gen"
            gen.mkdir()
            (gen / "screen.dart").write_text(dart_source)
            args = argparse.Namespace(
                blueprint=str(bp), contract=str(ct),
                gen_dir=str(gen), platform="flutter",
            )
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    cmd_check_codegen(args)
            except SystemExit:
                pass
            return json.loads(buf.getvalue())

    def test_multi_span_text_still_matched(self):
        """A long blueprint text split into several TextSpan must still be covered."""
        src = (
            "RichText(text: TextSpan(children: [\n"
            "  TextSpan(text: '已阅读并同意'),\n"
            "  TextSpan(text: '《用户服务协议》'),\n"
            "  TextSpan(text: '和'),\n"
            "  TextSpan(text: '《隐私政策》'),\n"
            "]))\n"
        )
        result = self._run_check(src, ["已阅读并同意《用户服务协议》和《隐私政策》"])
        errs = [e for e in result["errors"] if e["type"] == "low_text_coverage"]
        self.assertEqual(len(errs), 0)


class TestCanonicalTextCLI(unittest.TestCase):
    def test_canonically_equivalent_text_matches_without_hiding_copy_errors(self):
        # r41's title contains й encoded as either one or two Unicode code points.
        title = "«Договор онлайн микрокредита без залога»"
        formats = [("swiftui", "Screen.swift"), ("uikit", "Screen.m"),
                   ("compose", "Screen.kt"), ("android-views", "Screen.java"),
                   ("flutter", "screen.dart")]
        variants = [("NFD", "NFC", True), ("NFC", "NFD", True),
                    ("NFC", "different", False), ("NFC", "case", False),
                    ("NFC", "punctuation", False), ("NFC", "missing", False),
                    ("NFC", "compatibility", False)]
        incorrect = {
            "different": title.replace("онлайн", "оффлайн"),
            "case": title.replace("онлайн", "онлайН"),
            "punctuation": title.replace("онлайн ", "онлайн, "),
            "missing": title.replace("онлайн", "онлан"),
            "compatibility": title.replace(" ", "\u00a0"),
        }
        script = Path(__file__).resolve().parents[1] / "scripts/validate.py"
        for platform, filename in formats:
            for location in ["source", "resource"]:
                for bp_form, code_form, expected in variants:
                    with self.subTest(platform=platform, location=location, code_form=code_form):
                        blueprint_text = unicodedata.normalize(bp_form, title)
                        code_text = (incorrect[code_form] if code_form in incorrect
                                     else unicodedata.normalize(code_form, title))
                        with tempfile.TemporaryDirectory() as td:
                            work = Path(td)
                            (work / "bp.json").write_text(json.dumps({"components": [
                                {"texts": [{"value": blueprint_text}]}]}), encoding="utf-8")
                            (work / "ct.json").write_text('{"apis": []}', encoding="utf-8")
                            gen = work / "gen"
                            gen.mkdir()
                            (gen / filename).write_text(
                                f'let title = "{code_text}"' if location == "source" else 'class Screen {}',
                                encoding="utf-8")
                            if location == "resource":
                                (gen / "Localizable.strings").write_text(f'"title" = "{code_text}";', encoding="utf-8")
                            before = {p: p.read_bytes() for p in work.rglob('*') if p.is_file()}
                            run = subprocess.run([sys.executable, str(script), "check-codegen",
                                "--blueprint", str(work / "bp.json"), "--contract", str(work / "ct.json"),
                                "--gen-dir", str(gen), "--platform", platform], capture_output=True, text=True)
                            result = json.loads(run.stdout)
                            self.assertEqual(result["ok"], expected, result)
                            self.assertEqual(run.returncode, 0 if expected else 1)
                            self.assertEqual({p: p.read_bytes() for p in before}, before)


if __name__ == "__main__":
    unittest.main()
