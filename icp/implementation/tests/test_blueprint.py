"""Tests for blueprint.py — layout inference and data extraction."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from blueprint import (
    _count_distinct_bands,
    infer_layout,
    infer_width_constraint,
    is_background_layer,
    extract_text,
    extract_fill,
    parse_artboard_meta,
    build_component_blueprint,
    build_blueprint,
)


class TestCountDistinctBands(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_count_distinct_bands([]), 0)

    def test_single(self):
        self.assertEqual(_count_distinct_bands([100]), 1)

    def test_same_band(self):
        self.assertEqual(_count_distinct_bands([10, 12, 13], tolerance=4), 1)

    def test_two_bands(self):
        self.assertEqual(_count_distinct_bands([10, 12, 50, 52], tolerance=4), 2)

    def test_three_bands(self):
        self.assertEqual(_count_distinct_bands([10, 50, 100], tolerance=4), 3)


class TestInferLayout(unittest.TestCase):
    def test_single_child(self):
        self.assertEqual(infer_layout([{"left": 0, "top": 0, "width": 100, "height": 50}]), "single")

    def test_column(self):
        frames = [
            {"left": 16, "top": 100, "width": 300, "height": 24},
            {"left": 16, "top": 132, "width": 300, "height": 24},
            {"left": 16, "top": 164, "width": 300, "height": 24},
        ]
        self.assertEqual(infer_layout(frames), "column")

    def test_row(self):
        frames = [
            {"left": 10, "top": 50, "width": 80, "height": 40},
            {"left": 100, "top": 50, "width": 80, "height": 40},
            {"left": 190, "top": 50, "width": 80, "height": 40},
        ]
        self.assertEqual(infer_layout(frames), "row")

    def test_stack_full_overlap(self):
        frames = [
            {"left": 0, "top": 0, "width": 100, "height": 100},
            {"left": 0, "top": 0, "width": 100, "height": 100},
            {"left": 0, "top": 0, "width": 100, "height": 100},
        ]
        self.assertEqual(infer_layout(frames), "stack")

    def test_mixed_column_with_row_pairs(self):
        """Card with centered title + left-right detail rows = column."""
        frames = [
            {"left": 132, "top": 120, "width": 126, "height": 24},
            {"left": 124, "top": 152, "width": 142, "height": 36},
            {"left": 32, "top": 220, "width": 40, "height": 24},
            {"left": 279, "top": 220, "width": 79, "height": 24},
            {"left": 32, "top": 252, "width": 148, "height": 24},
            {"left": 279, "top": 252, "width": 79, "height": 24},
            {"left": 32, "top": 284, "width": 130, "height": 24},
            {"left": 273, "top": 284, "width": 85, "height": 24},
        ]
        self.assertEqual(infer_layout(frames), "column")


class TestInferWidthConstraint(unittest.TestCase):
    def test_fill_same_width(self):
        self.assertEqual(
            infer_width_constraint(
                {"left": 0, "width": 390, "top": 0, "height": 44},
                {"left": 0, "width": 390, "top": 0, "height": 844},
            ),
            "fill",
        )

    def test_fill_with_padding(self):
        self.assertEqual(
            infer_width_constraint(
                {"left": 16, "width": 358, "top": 0, "height": 44},
                {"left": 0, "width": 390, "top": 0, "height": 844},
            ),
            "fill",
        )

    def test_fixed(self):
        self.assertEqual(
            infer_width_constraint(
                {"left": 100, "width": 100, "top": 0, "height": 44},
                {"left": 0, "width": 390, "top": 0, "height": 844},
            ),
            "fixed",
        )


class TestIsBackgroundLayer(unittest.TestCase):
    def test_background(self):
        m = {"type": "artboard", "frame": {"left": 16, "top": 100, "width": 358, "height": 220}}
        cf = {"left": 16, "top": 100, "width": 358, "height": 220}
        self.assertTrue(is_background_layer(m, cf))

    def test_not_background_different_size(self):
        m = {"type": "artboard", "frame": {"left": 32, "top": 220, "width": 326, "height": 24}}
        cf = {"left": 16, "top": 100, "width": 358, "height": 220}
        self.assertFalse(is_background_layer(m, cf))

    def test_not_artboard(self):
        m = {"type": "textLayer", "frame": {"left": 16, "top": 100, "width": 358, "height": 220}}
        cf = {"left": 16, "top": 100, "width": 358, "height": 220}
        self.assertFalse(is_background_layer(m, cf))


class TestExtractText(unittest.TestCase):
    def test_with_text(self):
        m = {
            "text": {
                "value": "Hello",
                "spans": [{"font": "SF Pro", "size": 16, "weight": 400, "color": "#000", "line_height": 24, "align": "left", "letter_spacing": 0}],
            },
            "frame": {"left": 10, "top": 20, "width": 100, "height": 24},
        }
        result = extract_text(m)
        self.assertEqual(result["value"], "Hello")
        self.assertEqual(result["style"]["size"], 16)

    def test_without_text(self):
        self.assertIsNone(extract_text({"name": "box"}))


class TestExtractFill(unittest.TestCase):
    def test_solid(self):
        m = {"fills": [{"type": "solid", "color": "#fff"}]}
        result = extract_fill(m)
        self.assertEqual(result["type"], "solid")
        self.assertEqual(result["color"], "#fff")

    def test_gradient(self):
        m = {"fills": [{"type": "gradient", "gradient_type": 0, "stops": [{"color": "#a", "position": 0}]}]}
        result = extract_fill(m)
        self.assertEqual(result["type"], "gradient")
        self.assertEqual(len(result["stops"]), 1)

    def test_no_fills(self):
        self.assertIsNone(extract_fill({}))


class TestParseArtboardMeta(unittest.TestCase):
    def test_ios_1x(self):
        design = {"meta": {"device": "iOS @1x", "host": {"name": "figma"}}, "artboard": {"frame": {"width": 390, "height": 844}}}
        result = parse_artboard_meta(design)
        self.assertEqual(result["width"], 390)
        self.assertEqual(result["height"], 844)
        self.assertEqual(result["scale"], "1x")
        self.assertEqual(result["host"], "figma")

    def test_no_meta(self):
        result = parse_artboard_meta({})
        self.assertEqual(result["width"], 0)
        self.assertEqual(result["scale"], "1x")


class TestBuildComponentBlueprint(unittest.TestCase):
    def test_single_text_component(self):
        comp = {
            "name": "通知区",
            "role": "content",
            "description": "notice",
            "member_count": 1,
            "members": [{
                "id": "1", "name": "notice_text", "type": "textLayer",
                "frame": {"left": 16, "top": 340, "width": 358, "height": 44},
                "text": {"value": "Important notice", "spans": [{"font": "SF", "size": 14, "weight": 400, "color": "#333", "line_height": 22, "align": "left", "letter_spacing": 0}]},
                "visible": True, "opacity": 1, "is_system": False,
            }],
        }
        artboard = {"left": 0, "top": 0, "width": 390, "height": 844}
        bp = build_component_blueprint(comp, artboard)
        self.assertEqual(bp["name"], "通知区")
        self.assertEqual(len(bp["texts"]), 1)
        self.assertEqual(bp["texts"][0]["value"], "Important notice")

    def test_empty_component(self):
        comp = {"name": "empty", "role": "content", "description": "", "members": []}
        bp = build_component_blueprint(comp, {"left": 0, "top": 0, "width": 390, "height": 844})
        self.assertEqual(bp["layout"], "empty")


class TestBuildBlueprintIntegration(unittest.TestCase):
    """Integration test with minimal synthetic data."""

    def test_two_component_page(self):
        enriched = {
            "ok": True, "component_count": 3, "enriched_nodes": 5, "asset_required_count": 0,
            "components": [
                {"name": "页面根", "role": "content", "description": "root", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "标题", "role": "content", "description": "title", "member_count": 1,
                 "members": [{"id": "t1", "name": "Title", "type": "textLayer",
                              "frame": {"left": 16, "top": 60, "width": 343, "height": 28},
                              "text": {"value": "Welcome", "spans": [{"font": "SF", "size": 24, "weight": 700, "color": "#000", "line_height": 28, "align": "left", "letter_spacing": 0}]},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "按钮", "role": "action", "description": "CTA", "member_count": 2,
                 "members": [
                     {"id": "b1", "name": "btn_bg", "type": "artboard",
                      "frame": {"left": 16, "top": 700, "width": 343, "height": 48},
                      "fills": [{"type": "solid", "color": "#0066FF"}],
                      "visible": True, "opacity": 1, "is_system": False},
                     {"id": "b2", "name": "btn_label", "type": "textLayer",
                      "frame": {"left": 120, "top": 712, "width": 135, "height": 24},
                      "text": {"value": "Get Started", "spans": [{"font": "SF", "size": 16, "weight": 600, "color": "#fff", "line_height": 24, "align": "center", "letter_spacing": 0}]},
                      "visible": True, "opacity": 1, "is_system": False},
                 ]},
            ],
            "asset_required": [],
        }
        design = {
            "meta": {"device": "iOS @1x", "host": {"name": "figma"}, "sliceScale": 4, "id": "test"},
            "artboard": {"frame": {"width": 375, "height": 812}},
        }
        bp = build_blueprint(enriched, design)
        self.assertEqual(bp["artboard"]["width"], 375)
        self.assertEqual(bp["artboard"]["scale"], "1x")
        self.assertEqual(len(bp["components"]), 2)
        self.assertEqual(bp["components"][0]["name"], "标题")
        self.assertEqual(bp["components"][0]["texts"][0]["value"], "Welcome")
        self.assertEqual(bp["components"][1]["name"], "按钮")
        self.assertEqual(bp["components"][1]["texts"][0]["value"], "Get Started")
        self.assertEqual(bp["page_layout"], "column")
        self.assertEqual(bp["metrics"]["blueprint_texts"], 2)


if __name__ == "__main__":
    unittest.main()
