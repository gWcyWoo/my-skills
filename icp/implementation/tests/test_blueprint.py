"""Tests for blueprint.py — layout inference and data extraction."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from blueprint import (
    _count_distinct_bands,
    _to_resource_name,
    _extract_slice_asset,
    _build_parent_map,
    _dedup_ancestor_assets,
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


class TestToResourceName(unittest.TestCase):
    def test_slash_to_underscore(self):
        self.assertEqual(_to_resource_name("icon/navbar_back"), "icon_navbar_back")

    def test_dash_and_space(self):
        self.assertEqual(_to_resource_name("add-loan icon"), "add_loan_icon")

    def test_special_chars_stripped(self):
        self.assertEqual(_to_resource_name("Symbol Alternative.svg"), "symbol_alternative")

    def test_leading_digit_prefixed(self):
        self.assertEqual(_to_resource_name("3d_icon"), "ic_3d_icon")

    def test_empty_string(self):
        self.assertEqual(_to_resource_name(""), "")

    def test_cjk_name_uses_id_fallback(self):
        self.assertEqual(_to_resource_name("图标/返回", "abc123def"), "ic_abc123def")

    def test_cjk_name_no_id(self):
        self.assertEqual(_to_resource_name("返回"), "")


class TestExtractSliceAsset(unittest.TestCase):
    def test_match(self):
        member = {"id": "I92:2448;70:635", "name": "NavIcon", "type": "symbolInstence",
                  "frame": {"left": 16, "top": 50, "width": 32, "height": 32}}
        slice_map = {"I92:2448;70:635": {
            "id": "I92:2448;70:635", "name": "icon/navbar_back",
            "local_png": "assets/abc123.png", "local_svg": None}}
        a = _extract_slice_asset(member, slice_map)
        self.assertEqual(a["name"], "icon/navbar_back")
        self.assertEqual(a["file"], "assets/abc123.png")
        self.assertEqual(a["resource_name"], "icon_navbar_back")
        self.assertEqual(a["size"], {"width": 32, "height": 32})

    def test_no_match(self):
        member = {"id": "999", "name": "NotAnIcon", "type": "artboard"}
        a = _extract_slice_asset(member, {})
        self.assertIsNone(a)

    def test_svg_fallback(self):
        member = {"id": "s1", "name": "logo", "type": "artboard",
                  "frame": {"left": 0, "top": 0, "width": 24, "height": 24}}
        slice_map = {"s1": {"id": "s1", "name": "logo",
                            "local_png": None, "local_svg": "assets/logo.svg"}}
        a = _extract_slice_asset(member, slice_map)
        self.assertEqual(a["file"], "assets/logo.svg")

    def test_no_file_returns_none(self):
        member = {"id": "s2", "name": "broken", "type": "artboard",
                  "frame": {"left": 0, "top": 0, "width": 16, "height": 16}}
        slice_map = {"s2": {"id": "s2", "name": "broken",
                            "local_png": None, "local_svg": None}}
        a = _extract_slice_asset(member, slice_map)
        self.assertIsNone(a)

    def test_text_member_skipped(self):
        member = {"id": "t1", "name": "label", "type": "textLayer",
                  "text": {"value": "Hello", "spans": []},
                  "frame": {"left": 0, "top": 0, "width": 100, "height": 20}}
        slice_map = {"t1": {"id": "t1", "name": "label",
                            "local_png": "assets/label.png", "local_svg": None}}
        a = _extract_slice_asset(member, slice_map)
        self.assertIsNone(a)

    def test_text_ancestor_skipped(self):
        """Group containing textLayer descendant must not become an image asset."""
        member = {"id": "grp", "name": "BtnGroup", "type": "symbolInstence",
                  "frame": {"left": 0, "top": 0, "width": 56, "height": 56}}
        slice_map = {"grp": {"id": "grp", "name": "btn_service",
                             "local_png": "assets/service.png", "local_svg": None}}
        text_ancestor_ids = {"grp"}
        a = _extract_slice_asset(member, slice_map, text_ancestor_ids)
        self.assertIsNone(a)


class TestBuildBlueprintWithSlices(unittest.TestCase):
    def test_slices_produce_assets_with_file(self):
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "顶部导航", "role": "navigation", "description": "nav", "member_count": 1,
                 "members": [{"id": "icon1", "name": "NavBar", "type": "symbolInstence",
                              "frame": {"left": 16, "top": 50, "width": 32, "height": 32},
                              "visible": True, "opacity": 1, "is_system": False}]},
            ],
        }
        design = {"meta": {"device": "iOS @2x", "host": {"name": "figma"}},
                  "artboard": {"frame": {"width": 375, "height": 812}}}
        slices = [{"id": "icon1", "name": "icon/back",
                   "local_png": "assets/abc.png", "local_svg": None}]
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["file"], "assets/abc.png")
        self.assertEqual(assets[0]["resource_name"], "icon_back")
        self.assertEqual(bp["metrics"]["blueprint_assets"], 1)

    def test_artboard_slice_detected(self):
        """Non-symbolInstence node in slices should still produce an asset."""
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "图标区", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "art1", "name": "circle_bg", "type": "artboard",
                              "frame": {"left": 100, "top": 200, "width": 24, "height": 24},
                              "visible": True, "opacity": 1, "is_system": False}]},
            ],
        }
        design = {"meta": {"device": "iOS @1x", "host": {"name": "figma"}},
                  "artboard": {"frame": {"width": 375, "height": 812}}}
        slices = [{"id": "art1", "name": "icon_circle",
                   "local_png": "assets/circle.png", "local_svg": None}]
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["name"], "icon_circle")


    def test_container_member_slice_detected(self):
        """Slice on the container member (members[0]) must be detected."""
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "客服按钮", "role": "action", "description": "", "member_count": 2,
                 "members": [
                     {"id": "container1", "name": "BtnFrame", "type": "symbolInstence",
                      "frame": {"left": 300, "top": 700, "width": 56, "height": 56},
                      "visible": True, "opacity": 1, "is_system": False},
                     {"id": "label1", "name": "Label", "type": "textLayer",
                      "text": {"value": "客服", "spans": [{"font": "PingFang", "size": 12}]},
                      "frame": {"left": 310, "top": 720, "width": 36, "height": 16},
                      "visible": True, "opacity": 1, "is_system": False},
                 ]},
            ],
        }
        design = {"meta": {"device": "iOS @2x", "host": {"name": "figma"}},
                  "artboard": {"frame": {"width": 375, "height": 812}}}
        slices = [{"id": "container1", "name": "icon/service",
                   "local_png": "assets/service.png", "local_svg": None}]
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["file"], "assets/service.png")

    def test_system_member_excluded(self):
        """System chrome members should not produce assets."""
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "状态栏", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "sys1", "name": "StatusBar", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 44},
                              "visible": True, "opacity": 1, "is_system": True}]},
            ],
        }
        design = {"meta": {"device": "iOS @2x", "host": {"name": "figma"}},
                  "artboard": {"frame": {"width": 375, "height": 812}}}
        slices = [{"id": "sys1", "name": "statusbar",
                   "local_png": "assets/statusbar.png", "local_svg": None}]
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        self.assertEqual(len(assets), 0)


class TestBuildParentMap(unittest.TestCase):
    def test_flat_tree(self):
        artboard = {"id": "root", "layers": [
            {"id": "a"}, {"id": "b"},
        ]}
        pm, tai = _build_parent_map(artboard)
        self.assertIsNone(pm["root"])
        self.assertEqual(pm["a"], "root")
        self.assertEqual(pm["b"], "root")
        self.assertEqual(tai, set())

    def test_nested_tree(self):
        artboard = {"id": "root", "layers": [
            {"id": "group", "layers": [
                {"id": "child1"}, {"id": "child2"},
            ]},
        ]}
        pm, tai = _build_parent_map(artboard)
        self.assertEqual(pm["group"], "root")
        self.assertEqual(pm["child1"], "group")
        self.assertEqual(pm["child2"], "group")
        self.assertEqual(tai, set())

    def test_empty_artboard(self):
        pm, tai = _build_parent_map({})
        self.assertEqual(pm, {})
        self.assertEqual(tai, set())

    def test_text_ancestor_collected(self):
        artboard = {"id": "root", "layers": [
            {"id": "group", "type": "symbolInstence", "layers": [
                {"id": "label", "type": "textLayer"},
                {"id": "icon", "type": "shapeLayer"},
            ]},
        ]}
        pm, tai = _build_parent_map(artboard)
        self.assertIn("group", tai)
        self.assertNotIn("label", tai)
        self.assertNotIn("icon", tai)

    def test_deep_text_ancestor(self):
        artboard = {"id": "root", "layers": [
            {"id": "outer", "type": "artboard", "layers": [
                {"id": "inner", "type": "symbolInstence", "layers": [
                    {"id": "txt", "type": "textLayer"},
                ]},
            ]},
        ]}
        pm, tai = _build_parent_map(artboard)
        self.assertIn("outer", tai)
        self.assertIn("inner", tai)


class TestDedupAncestorAssets(unittest.TestCase):
    def test_parent_child_both_exported(self):
        """Child is removed when its parent is also in the asset set."""
        parent_map = {"root": None, "group": "root", "icon": "group"}
        assets = [
            {"id": "group", "name": "card", "file": "a.png", "resource_name": "card"},
            {"id": "icon", "name": "star", "file": "b.png", "resource_name": "star"},
        ]
        result = _dedup_ancestor_assets(assets, parent_map)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "group")

    def test_siblings_both_kept(self):
        """Siblings (no ancestor relation) are both kept."""
        parent_map = {"root": None, "a": "root", "b": "root"}
        assets = [
            {"id": "a", "name": "icon_a", "file": "a.png", "resource_name": "icon_a"},
            {"id": "b", "name": "icon_b", "file": "b.png", "resource_name": "icon_b"},
        ]
        result = _dedup_ancestor_assets(assets, parent_map)
        self.assertEqual(len(result), 2)

    def test_single_asset_unchanged(self):
        parent_map = {"root": None, "a": "root"}
        assets = [{"id": "a", "name": "x", "file": "x.png", "resource_name": "x"}]
        result = _dedup_ancestor_assets(assets, parent_map)
        self.assertEqual(len(result), 1)

    def test_empty_parent_map_passthrough(self):
        assets = [
            {"id": "a", "name": "x", "file": "x.png", "resource_name": "x"},
            {"id": "b", "name": "y", "file": "y.png", "resource_name": "y"},
        ]
        result = _dedup_ancestor_assets(assets, {})
        self.assertEqual(len(result), 2)

    def test_grandparent_dedup(self):
        """Grandchild is removed when grandparent is in the set (but not parent)."""
        parent_map = {"root": None, "gp": "root", "p": "gp", "child": "p"}
        assets = [
            {"id": "gp", "name": "group", "file": "g.png", "resource_name": "group"},
            {"id": "child", "name": "dot", "file": "d.png", "resource_name": "dot"},
        ]
        result = _dedup_ancestor_assets(assets, parent_map)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "gp")


class TestBuildBlueprintAncestorDedup(unittest.TestCase):
    def test_parent_child_slices_deduped(self):
        """Integration: parent+child in slices → only parent in blueprint assets."""
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "卡片", "role": "content", "description": "", "member_count": 2,
                 "members": [
                     {"id": "card", "name": "CardGroup", "type": "symbolInstence",
                      "frame": {"left": 16, "top": 100, "width": 343, "height": 200},
                      "visible": True, "opacity": 1, "is_system": False},
                     {"id": "star", "name": "StarIcon", "type": "artboard",
                      "frame": {"left": 300, "top": 110, "width": 24, "height": 24},
                      "visible": True, "opacity": 1, "is_system": False},
                 ]},
            ],
        }
        design = {
            "meta": {"device": "iOS @2x", "host": {"name": "figma"}},
            "artboard": {"id": "root", "frame": {"width": 375, "height": 812},
                         "layers": [{"id": "card", "layers": [{"id": "star"}]}]},
        }
        slices = [
            {"id": "card", "name": "card_bg", "local_png": "assets/card.png", "local_svg": None},
            {"id": "star", "name": "icon/star", "local_png": "assets/star.png", "local_svg": None},
        ]
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["resource_name"], "card_bg")
        self.assertEqual(bp["metrics"]["blueprint_assets"], 1)


    def test_cross_component_dedup(self):
        """Parent in component A, child in component B → child filtered globally."""
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "卡片", "role": "content", "description": "", "member_count": 1,
                 "members": [
                     {"id": "card", "name": "CardGroup", "type": "symbolInstence",
                      "frame": {"left": 16, "top": 100, "width": 343, "height": 200},
                      "visible": True, "opacity": 1, "is_system": False},
                 ]},
                {"name": "星标", "role": "content", "description": "", "member_count": 1,
                 "members": [
                     {"id": "star", "name": "StarIcon", "type": "artboard",
                      "frame": {"left": 300, "top": 110, "width": 24, "height": 24},
                      "visible": True, "opacity": 1, "is_system": False},
                 ]},
            ],
        }
        design = {
            "meta": {"device": "iOS @2x", "host": {"name": "figma"}},
            "artboard": {"id": "root", "frame": {"width": 375, "height": 812},
                         "layers": [{"id": "card", "layers": [{"id": "star"}]}]},
        }
        slices = [
            {"id": "card", "name": "card_bg", "local_png": "assets/card.png", "local_svg": None},
            {"id": "star", "name": "icon/star", "local_png": "assets/star.png", "local_svg": None},
        ]
        bp = build_blueprint(enriched, design, slices)
        card_assets = bp["components"][0].get("assets", [])
        star_assets = bp["components"][1].get("assets", [])
        self.assertEqual(len(card_assets), 1)
        self.assertEqual(card_assets[0]["resource_name"], "card_bg")
        self.assertEqual(len(star_assets), 0)
        self.assertEqual(bp["metrics"]["blueprint_assets"], 1)


    def test_text_descendant_excluded(self):
        """Group containing textLayer child → no asset even when exported."""
        enriched = {
            "components": [
                {"name": "root", "role": "content", "description": "", "member_count": 1,
                 "members": [{"id": "root", "name": "Page", "type": "artboard",
                              "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
                              "visible": True, "opacity": 1, "is_system": False}]},
                {"name": "按钮", "role": "action", "description": "", "member_count": 2,
                 "members": [
                     {"id": "btn", "name": "ServiceBtn", "type": "symbolInstence",
                      "frame": {"left": 300, "top": 700, "width": 56, "height": 56},
                      "visible": True, "opacity": 1, "is_system": False},
                     {"id": "lbl", "name": "Label", "type": "textLayer",
                      "text": {"value": "客服", "spans": [{"font": "PingFang", "size": 12}]},
                      "frame": {"left": 310, "top": 720, "width": 36, "height": 16},
                      "visible": True, "opacity": 1, "is_system": False},
                 ]},
            ],
        }
        design = {
            "meta": {"device": "iOS @2x", "host": {"name": "figma"}},
            "artboard": {"id": "root", "frame": {"width": 375, "height": 812},
                         "layers": [{"id": "btn", "type": "symbolInstence",
                                     "layers": [{"id": "lbl", "type": "textLayer"}]}]},
        }
        slices = [{"id": "btn", "name": "btn_service",
                   "local_png": "assets/service.png", "local_svg": None}]
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        self.assertEqual(len(assets), 0)
        self.assertEqual(bp["metrics"]["blueprint_assets"], 0)


class TestResourceNameCollision(unittest.TestCase):
    """resource_name 冲突时自动加后缀避免文件覆盖。"""

    def _make_env(self, slice_names):
        members = [
            {"id": "root", "name": "Page", "type": "artboard",
             "frame": {"left": 0, "top": 0, "width": 375, "height": 812},
             "visible": True, "opacity": 1, "is_system": False}
        ]
        slices = []
        layers = []
        for i, sn in enumerate(slice_names):
            mid = f"m{i}"
            members.append(
                {"id": mid, "name": sn, "type": "shapeLayer",
                 "frame": {"left": 10 * i, "top": 10, "width": 24, "height": 24},
                 "visible": True, "opacity": 1, "is_system": False})
            slices.append({"id": mid, "name": sn,
                           "local_png": f"assets/{mid}.png", "local_svg": None})
            layers.append({"id": mid, "type": "shapeLayer"})
        enriched = {"components": [
            {"name": "root", "role": "content", "description": "", "member_count": 1,
             "members": [members[0]]},
            {"name": "icons", "role": "action", "description": "",
             "member_count": len(members) - 1, "members": members},
        ]}
        design = {"meta": {"device": "iOS @2x", "host": {"name": "figma"}},
                  "artboard": {"id": "root",
                               "frame": {"width": 375, "height": 812},
                               "layers": layers}}
        return enriched, design, slices

    def test_collision_suffixed(self):
        enriched, design, slices = self._make_env(["icon/arrow", "icon-arrow"])
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        names = [a["resource_name"] for a in assets]
        self.assertEqual(len(names), 2)
        self.assertIn("icon_arrow", names)
        self.assertIn("icon_arrow_2", names)

    def test_no_collision_unchanged(self):
        enriched, design, slices = self._make_env(["icon/back", "icon/close"])
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        names = [a["resource_name"] for a in assets]
        self.assertEqual(sorted(names), ["icon_back", "icon_close"])

    def test_triple_collision(self):
        enriched, design, slices = self._make_env(
            ["icon/star", "icon-star", "icon star"])
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        names = sorted([a["resource_name"] for a in assets])
        self.assertEqual(names, ["icon_star", "icon_star_2", "icon_star_3"])


    def test_collision_skips_existing_suffixed_name(self):
        """icon_arrow_2 already exists → suffix jumps to _3."""
        enriched, design, slices = self._make_env(
            ["icon/arrow", "icon-arrow", "icon_arrow_2"])
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        names = [a["resource_name"] for a in assets]
        self.assertEqual(len(set(names)), len(names), f"duplicates: {names}")
        self.assertIn("icon_arrow", names)
        self.assertIn("icon_arrow_2", names)
        self.assertIn("icon_arrow_3", names)


    def test_same_file_keeps_one_name(self):
        """Same file under colliding names → same resource_name, no suffix."""
        enriched, design, slices = self._make_env(["icon/arrow", "icon-arrow"])
        slices[0]["local_png"] = "assets/shared.png"
        slices[1]["local_png"] = "assets/shared.png"
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        names = [a["resource_name"] for a in assets]
        self.assertTrue(all(n == "icon_arrow" for n in names),
                        f"same file should share name: {names}")

    def test_mixed_same_and_different_files(self):
        """Two same-file + one different-file → 2 names total."""
        enriched, design, slices = self._make_env(
            ["icon/arrow", "icon-arrow", "icon arrow x"])
        slices[0]["local_png"] = "assets/shared.png"
        slices[1]["local_png"] = "assets/shared.png"
        slices[2]["local_png"] = "assets/other.png"
        slices[2]["name"] = "icon/arrow"
        bp = build_blueprint(enriched, design, slices)
        assets = bp["components"][0].get("assets", [])
        names = [a["resource_name"] for a in assets]
        unique = set(names)
        self.assertEqual(len(unique), 2, f"expected 2 unique names: {names}")


if __name__ == "__main__":
    unittest.main()
