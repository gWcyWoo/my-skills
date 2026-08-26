"""Tests for struct_diff.py — text matching and hierarchy checking."""
import os
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


if __name__ == "__main__":
    unittest.main()
