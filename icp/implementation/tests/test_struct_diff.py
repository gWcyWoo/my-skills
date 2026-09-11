"""Tests for struct_diff.py — text matching and hierarchy checking."""
import json
import os
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from struct_diff import (
    normalize_text,
    match_texts,
    parse_view_tree,
    extract_view_texts,
    count_interactive,
    check_hierarchy,
    build_diff,
    _parse_html,
)

SAMPLE_VIEW_TREE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" text="" bounds="[0,0][1080,2340]">
    <node class="android.widget.TextView" text="Способ оплаты" bounds="[60,120][300,148]" clickable="false" resource-id="" content-desc="" />
    <node class="android.widget.TextView" text="6 000 000 ₸" bounds="[124,152][266,188]" clickable="false" resource-id="" content-desc="" />
    <node class="android.widget.TextView" text="Пеня" bounds="[32,220][72,244]" clickable="false" resource-id="" content-desc="" />
    <node class="android.widget.Button" text="Мгновенно оплатить" bounds="[16,436][374,492]" clickable="true" resource-id="" content-desc="" />
  </node>
</hierarchy>
"""


class TestNormalizeText(unittest.TestCase):
    def test_strip_and_lower(self):
        self.assertEqual(normalize_text("  Hello World "), "hello world")

    def test_collapse_whitespace(self):
        self.assertEqual(normalize_text("a\n  b\t c"), "a b c")

    def test_nfkc_fullwidth(self):
        self.assertEqual(normalize_text("％１００"), "%100")

    def test_strip_zero_width(self):
        self.assertEqual(normalize_text("登​录"), "登录")

    def test_strip_word_joiner(self):
        self.assertEqual(normalize_text("a⁠b"), "ab")


class TestMatchTexts(unittest.TestCase):
    def test_exact_match(self):
        result = match_texts(["hello", "world"], ["hello", "world", "extra"])
        self.assertEqual(result["matched"], ["hello", "world"])
        self.assertEqual(result["missing"], [])

    def test_partial_match(self):
        result = match_texts(["hello", "missing"], ["hello"])
        self.assertEqual(result["matched"], ["hello"])
        self.assertEqual(result["missing"], ["missing"])

    def test_nbsp_normalized_match(self):
        result = match_texts(["6 000 000 ₸"], ["6 000 000 ₸"])
        self.assertEqual(len(result["matched"]), 1)

    def test_no_substring_false_positive(self):
        result = match_texts(["Пеня"], ["Пеня за просрочку"])
        self.assertEqual(result["matched"], [])
        self.assertEqual(result["missing"], ["Пеня"])

    def test_empty_expected(self):
        result = match_texts([], ["anything"])
        self.assertEqual(result["matched"], [])
        self.assertEqual(result["missing"], [])


class TestParseViewTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
        self.tmp.write(SAMPLE_VIEW_TREE_XML)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_parse_nodes(self):
        nodes = parse_view_tree(Path(self.tmp.name))
        self.assertEqual(len(nodes), 5)

    def test_extract_texts(self):
        nodes = parse_view_tree(Path(self.tmp.name))
        texts = extract_view_texts(nodes)
        self.assertIn("Способ оплаты", texts)
        self.assertIn("Мгновенно оплатить", texts)

    def test_count_interactive(self):
        nodes = parse_view_tree(Path(self.tmp.name))
        self.assertEqual(count_interactive(nodes), 1)


class TestExtractViewTexts(unittest.TestCase):
    def test_duplicate_text_content_desc_not_doubled(self):
        """Same string in text and content_desc must produce one pool entry, not two."""
        nodes = [
            {"text": "提交", "content_desc": "提交", "clickable": True},
        ]
        texts = extract_view_texts(nodes)
        self.assertEqual(texts.count("提交"), 1)

    def test_different_text_content_desc_both_emitted(self):
        nodes = [
            {"text": "Submit", "content_desc": "提交按钮", "clickable": True},
        ]
        texts = extract_view_texts(nodes)
        self.assertIn("Submit", texts)
        self.assertIn("提交按钮", texts)


class TestCheckHierarchy(unittest.TestCase):
    def test_correct_order(self):
        blueprint = {
            "components": [
                {"name": "nav", "texts": [{"value": "Способ оплаты"}]},
                {"name": "card", "texts": [{"value": "Пеня"}]},
                {"name": "button", "texts": [{"value": "Мгновенно оплатить"}]},
            ]
        }
        nodes = [
            {"text": "Способ оплаты", "content_desc": ""},
            {"text": "Пеня", "content_desc": ""},
            {"text": "Мгновенно оплатить", "content_desc": ""},
        ]
        result = check_hierarchy(blueprint, nodes)
        self.assertTrue(result["order_correct"])

    def test_wrong_order(self):
        blueprint = {
            "components": [
                {"name": "A", "texts": [{"value": "second"}]},
                {"name": "B", "texts": [{"value": "first"}]},
            ]
        }
        nodes = [
            {"text": "first", "content_desc": ""},
            {"text": "second", "content_desc": ""},
        ]
        result = check_hierarchy(blueprint, nodes)
        self.assertFalse(result["order_correct"])


class TestBuildDiff(unittest.TestCase):
    def test_full_match(self):
        blueprint = {
            "components": [
                {"name": "title", "role": "content", "texts": [{"value": "Hello"}]},
                {"name": "btn", "role": "action", "texts": [{"value": "Click"}]},
            ]
        }
        nodes = [
            {"text": "Hello", "content_desc": "", "clickable": False},
            {"text": "Click", "content_desc": "", "clickable": True},
        ]
        diff = build_diff(blueprint, nodes)
        self.assertEqual(diff["texts"]["matched"], 2)
        self.assertEqual(diff["texts"]["missing"], [])
        self.assertEqual(diff["components"]["found_by_text"], 2)

    def test_missing_text(self):
        blueprint = {
            "components": [
                {"name": "title", "role": "content", "texts": [{"value": "Hello"}, {"value": "Missing"}]},
            ]
        }
        nodes = [{"text": "Hello", "content_desc": "", "clickable": False}]
        diff = build_diff(blueprint, nodes)
        self.assertEqual(diff["texts"]["matched"], 1)
        self.assertEqual(diff["texts"]["missing"], ["Missing"])

    def test_textless_component_by_content_desc(self):
        blueprint = {
            "components": [
                {"name": "title", "role": "content", "texts": [{"value": "Hello"}]},
                {"name": "客服浮动按钮", "role": "action", "texts": []},
            ]
        }
        nodes = [
            {"text": "Hello", "content_desc": "", "resource_id": "", "clickable": False},
            {"text": "", "content_desc": "客服浮动按钮", "resource_id": "", "clickable": True},
        ]
        diff = build_diff(blueprint, nodes)
        self.assertIn("客服浮动按钮", diff["components"]["found_by_id"])
        self.assertEqual(diff["components"]["missing"], [])

    def test_textless_component_substring_content_desc(self):
        """Chinese component name matches as substring in content_desc."""
        blueprint = {
            "components": [
                {"name": "关闭", "role": "action", "texts": []},
            ]
        }
        nodes = [
            {"text": "", "content_desc": "关闭按钮", "resource_id": "", "clickable": True},
        ]
        diff = build_diff(blueprint, nodes)
        self.assertIn("关闭", diff["components"]["found_by_id"])

    def test_gate_low_component_coverage_still_passes(self):
        """comp_coverage is informational, not a gate condition."""
        blueprint = {
            "page_layout": "column",
            "components": [
                {"name": "title", "role": "content", "texts": [{"value": "Hello"}]},
                {"name": "icon_a", "role": "content", "texts": []},
                {"name": "icon_b", "role": "content", "texts": []},
                {"name": "icon_c", "role": "content", "texts": []},
            ],
        }
        vt = '<?xml version="1.0"?><hierarchy><node class="x" text="Hello" bounds="[0,0][1,1]" clickable="false" resource-id="" content-desc="" /></hierarchy>'
        gate = self._run_gate(blueprint, vt)
        self.assertTrue(gate["ok"])
        self.assertLess(gate["component_coverage"], 0.5)

    def _run_gate(self, blueprint, view_tree_xml):
        with tempfile.TemporaryDirectory() as td:
            bp_path = os.path.join(td, "bp.json")
            vt_path = os.path.join(td, "vt.xml")
            out_path = os.path.join(td, "out.json")
            with open(bp_path, "w") as f:
                json.dump(blueprint, f)
            with open(vt_path, "w") as f:
                f.write(view_tree_xml)
            script = str(Path(__file__).resolve().parent.parent / "scripts" / "struct_diff.py")
            subprocess.run(
                [sys.executable, script, "--view-tree", vt_path,
                 "--blueprint", bp_path, "--output", out_path],
                check=False, capture_output=True)
            with open(out_path) as f:
                return json.load(f)["gate"]

    def test_match_texts_multiset(self):
        result = match_texts(["OK", "OK", "OK"], ["OK"])
        self.assertEqual(len(result["matched"]), 1)
        self.assertEqual(len(result["missing"]), 2)

    def test_zero_width_text_not_counted_as_expected(self):
        """Zero-width-only texts must not inflate expected count."""
        blueprint = {
            "page_layout": "column",
            "components": [
                {"name": "a", "role": "content", "texts": [
                    {"value": "Hello"},
                    {"value": "​"},
                ]},
            ],
        }
        nodes = [{"text": "Hello", "resource_id": "", "content_desc": "", "clickable": False}]
        diff = build_diff(blueprint, nodes)
        self.assertEqual(diff["texts"]["expected"], 1)
        self.assertEqual(diff["texts"]["matched"], 1)
        self.assertEqual(diff["texts"]["missing"], [])

    def test_zero_width_text_excluded_from_hierarchy(self):
        """Zero-width texts must not produce phantom hierarchy matches."""
        result = check_hierarchy(
            {"page_layout": "column", "components": [
                {"name": "top", "frame": {"top": 0, "left": 0},
                 "texts": [{"value": "​"}]},
                {"name": "bottom", "frame": {"top": 100, "left": 0},
                 "texts": [{"value": "Real"}]},
            ]},
            [{"text": "​", "resource_id": "", "content_desc": "", "clickable": False},
             {"text": "Real", "resource_id": "", "content_desc": "", "clickable": False}],
        )
        self.assertNotIn("top", result["components_with_text"])


class TestParseHtml(unittest.TestCase):
    def test_data_value_not_captured(self):
        """data-value= must not be extracted as visible text."""
        nodes = _parse_html('<div class="sel" data-value="已完成"><span class="arrow"></span></div>')
        texts = [n["text"] for n in nodes if n["text"]]
        self.assertNotIn("已完成", texts)

    def test_real_value_captured(self):
        """Standalone value= on input should be extracted."""
        nodes = _parse_html('<input value="已完成">')
        texts = [n["text"] for n in nodes if n["text"]]
        self.assertIn("已完成", texts)


if __name__ == "__main__":
    unittest.main()
