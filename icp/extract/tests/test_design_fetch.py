"""design_fetch 契约测试 — 设计稿引用按地址分流到平台适配器。"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "design_fetch.py"
SPEC = importlib.util.spec_from_file_location("design_fetch", SCRIPT)
DESIGN_FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESIGN_FETCH)

SELFHOST = "https://47.84.143.250.sslip.io"


def run(argv, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = DESIGN_FETCH.main(argv, **kw)
    lines = buf.getvalue().strip().splitlines()
    assert len(lines) == 1, f"stdout 须恰好一行 JSON: {lines!r}"
    return code, json.loads(lines[0])


class CheckSelfhostRefTest(unittest.TestCase):
    def test_design_link_yields_project_and_design_ids(self):
        # 就是平台里打开设计图时地址栏的链接；参数顺序与其它参数不影响
        for ref in (f"{SELFHOST}/?project=17&design=748",
                    f" {SELFHOST}?design=748&project=17 ",
                    f"{SELFHOST}/?share=abc&project=17&design=748#top"):
            with self.subTest(ref=ref):
                code, out = run(["check", "--ref", ref])
                self.assertEqual(code, 0, out)
                self.assertEqual(out, {"ok": True, "design": "selfhost",
                                       "project_id": 17, "design_id": 748})


class CheckLanhuRefTest(unittest.TestCase):
    def test_routes_lanhu_url_to_lanhu_adapter(self):
        code, out = run(["check", "--ref",
                         "https://lanhuapp.com/web/#/item/project/detailDetach"
                         "?pid=p-77&project_id=p-77&fromEditor=true&image_id=img-42"])
        self.assertEqual(code, 0)
        self.assertEqual(
            (out["ok"], out["design"], out["image_id"], out["project_id"]),
            (True, "lanhu", "img-42", "p-77"))

    def test_lanhu_url_without_image_id_is_bad_ref(self):
        code, out = run(["check", "--ref",
                         "https://lanhuapp.com/web/#/item/project/stage?tid=t-1&pid=p-77"])
        self.assertNotEqual(code, 0)
        self.assertEqual([e["type"] for e in out["errors"]], ["bad_ref"])


class FetchLanhuRefTest(unittest.TestCase):
    def test_lanhu_fetch_is_handled_by_lanhu_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"HOME": td}, clear=False):
                os.environ.pop("LANHU_COOKIE", None)
                code, out = run(["fetch", "--out-dir", str(Path(td) / "out"), "--ref",
                                 "https://lanhuapp.com/web/#/item/project/detailDetach"
                                 "?pid=p-77&project_id=p-77&image_id=img-42"])
        self.assertNotEqual(code, 0)
        self.assertEqual([e["type"] for e in out["errors"]], ["no_cookie"])
        # 蓝湖适配器自己的提示，证明没有被分到自建平台
        self.assertIn("LANHU_COOKIE", out["errors"][0]["detail"])

    def test_lanhu_cookie_reaches_lanhu_http_verbatim(self):
        # design_fetch 已把 scripts 目录放进 sys.path；只替换蓝湖的网络边界
        lanhu = importlib.import_module("lanhu_fetch")
        seen = []

        def offline(url, cookie, timeout=30):
            seen.append(cookie)
            raise RuntimeError("offline")

        with tempfile.TemporaryDirectory() as td, patch.object(lanhu, "http_get", offline):
            code, out = run(["fetch", "--out-dir", str(Path(td) / "out"), "--cookie=-x=1",
                             "--ref", "https://lanhuapp.com/web/#/item/project/detailDetach"
                                      "?pid=p-77&project_id=p-77&image_id=img-42"])
            self.assertFalse((Path(td) / "out").exists())
        self.assertNotEqual(code, 0)
        self.assertEqual(seen, ["-x=1"])


class CheckUnknownRefTest(unittest.TestCase):
    def test_unregistered_refs_are_unknown_design(self):
        for ref in ("https://www.figma.com/file/abc",
                    "见上一行",
                    "https://lanhuapp.com.evil.com/web/#/item?pid=p-1&image_id=i-1",
                    f"{SELFHOST}.evil.com/?project=17&design=748"):
            with self.subTest(ref=ref):
                code, out = run(["check", "--ref", ref])
                self.assertNotEqual(code, 0)
                self.assertEqual(out["ok"], False)
                self.assertEqual([e["type"] for e in out["errors"]], ["unknown_design"])


class CheckBadSelfhostRefTest(unittest.TestCase):
    def test_malformed_selfhost_refs_are_bad_ref(self):
        for ref in (# 旧的「项目名-平台-设计稿名」写法不再支持
                    f"{SELFHOST}:会员中心-安卓设计图-首页",
                    f"{SELFHOST}/",
                    f"{SELFHOST}/?project=17",
                    f"{SELFHOST}/?design=748",
                    f"{SELFHOST}/?project=17&prototype=12",
                    f"{SELFHOST}/?project=17&design=",
                    f"{SELFHOST}/?project=17&design=748&design=749",
                    f"{SELFHOST}/?project=0&design=748",
                    f"{SELFHOST}/?project=17&design=-748",
                    f"{SELFHOST}/?project=17&design=7.5",
                    f"{SELFHOST}/?project=17&design=+748",
                    f"{SELFHOST}/?project=17&design=%20748",
                    f"{SELFHOST}/?project=17&design=٧٤٨",
                    f"{SELFHOST}/?project=17&design=abc",
                    f"{SELFHOST}/projects?project=17&design=748",
                    f"{SELFHOST}:8443/?project=17&design=748"):
            with self.subTest(ref=ref):
                code, out = run(["check", "--ref", ref])
                self.assertNotEqual(code, 0)
                self.assertEqual(out["ok"], False)
                self.assertEqual([e["type"] for e in out["errors"]], ["bad_ref"])


# ---------------------------------------------------------------- 自建平台 fetch

PROJECT = "哈萨克标准化产品-Nomad Credit"
ROOT = "1644:2015"
COOKIE = "sess=abc"
REF = f"{SELFHOST}/?project=17&design=802"


def layer(lid, parent, name, ltype, x, y, w, h, **style):
    base = {
        "id": lid, "parentId": parent, "name": name, "type": ltype,
        "x": x, "y": y, "width": w, "height": h,
        "frameWidth": 390, "frameHeight": 844, "opacity": 1,
        "cornerRadii": [0, 0, 0, 0],
        "fillColor": None, "fillOpacity": 0,
        "strokeColor": None, "strokeOpacity": 0, "strokeWeight": 1,
        "isLayoutOnly": False, "textContent": "",
        "fontFamily": None, "fontStyle": None, "fontWeight": 0, "fontSize": 0,
        "textAlign": None, "letterSpacingValue": 0, "letterSpacingUnit": None,
        "lineHeightValue": 0, "lineHeightUnit": None,
        "textCaptured": False, "styleCaptured": True,
    }
    base.update(style)
    return base


def page_layers(title):
    return [
        layer("1644:2066", ROOT, "导航栏", "INSTANCE", 0, 44, 390, 44,
              fillColor="#FFFFFF", fillOpacity=1),
        layer("I1644:2066;41:910", "1644:2066", "Title", "TEXT", 52, 50, 200, 28,
              textContent=title, fillColor="#121212", fillOpacity=1,
              fontFamily="SF Pro", fontStyle="Bold", fontWeight=700, fontSize=18,
              textAlign="LEFT", lineHeightValue=28, lineHeightUnit="PIXELS",
              letterSpacingValue=10, letterSpacingUnit="PERCENT", textCaptured=True),
        layer("1653:3000", ROOT, "卡片", "FRAME", 16, 120, 358, 200,
              cornerRadii=[12, 8, 4, 0], fillColor="#337B55", fillOpacity=0.06,
              strokeColor="#E5E5E5", strokeOpacity=1, strokeWeight=1),
        layer("1653:3103", "1653:3000", "选择框", "INSTANCE", 40, 140, 24, 24),
        layer("1653:3104", "1653:3103", "勾", "VECTOR", 44, 144, 16, 16,
              fillColor="#D9456D", fillOpacity=1),
    ]


def asset(aid, name, platform, created, layers, slices=()):
    return {
        "id": aid, "name": name, "kind": "ui", "contentType": "image/png",
        "figmaPlatform": platform, "createdAt": created,
        "layers": layers, "slices": list(slices), "preview": f"/api/assets/{aid}",
    }


def slice_(aid, sid, name, x, y, w, h):
    return {"assetId": aid, "id": sid, "name": name, "x": x, "y": y,
            "width": w, "height": h, "frameWidth": 390, "frameHeight": 844,
            "preview": f"/api/assets/{aid}/slices/{sid}"}


class FakePlatform:
    """外部平台 HTTP 边界替身：按 URL 返回固定响应，并记录每次请求。"""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, url, cookie):
        self.requests.append((url, cookie))
        if url not in self.routes:
            raise RuntimeError(f"HTTP 404: {url}")
        body = self.routes[url]
        if isinstance(body, Exception):
            raise body
        return body if isinstance(body, bytes) else json.dumps(body).encode()


def platform_routes(assets, extra=None):
    routes = {
        f"{SELFHOST}/api/projects": {"projects": [
            {"id": 17, "name": PROJECT},
            {"id": 18, "name": f"{PROJECT} 2"},
        ]},
        f"{SELFHOST}/api/projects/17/assets": {"assets": assets},
        f"{SELFHOST}/api/projects/18/assets": {"assets": []},
    }
    for a in assets:
        routes[f"{SELFHOST}/api/assets/{a['id']}"] = f"PNG-{a['id']}".encode()
    routes.update(extra or {})
    return routes


def fetch(tmp, platform, ref=REF, cookie=COOKIE):
    argv = ["fetch", "--ref", ref, "--out-dir", str(tmp)]
    if cookie is not None:
        argv += ["--cookie", cookie]
    return run(argv, http_get=platform)


class SelfhostFetchSelectionTest(unittest.TestCase):
    def test_fetches_exactly_the_linked_upload(self):
        # 链接钉住一次上传：同画板的旧版、之后的重传版、同名 iOS 版与原型都不取
        old = asset(797, "Figma · 调查问卷-1（俄语）", "android",
                    "2026-10-20T00:00:00.000Z", page_layers("旧版标题"))
        linked = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                       "2026-10-25T00:00:00.000Z", page_layers("链接版标题"))
        newer = asset(805, "Figma · 调查问卷-1（俄语）", "android",
                      "2026-10-28T00:00:00.000Z", page_layers("重传版标题"))
        ios = asset(810, "Figma · 调查问卷-1（俄语）", "ios",
                    "2026-10-27T00:00:00.000Z",
                    [layer("9:1", "9:0", "iOS 标题", "TEXT", 0, 0, 10, 10)])
        prototype = dict(asset(830, "Figma · 调查问卷-1（俄语）", "android",
                               "2026-10-29T00:00:00.000Z", page_layers("原型")), kind="axure")
        platform = FakePlatform(platform_routes([old, linked, newer, ios, prototype]))

        with tempfile.TemporaryDirectory() as td:
            code, out = fetch(Path(td), platform)
            self.assertEqual(code, 0, out)
            self.assertEqual((out["ok"], out["design_id"], out["design_name"]),
                             (True, 802, "调查问卷-1（俄语）"))
            self.assertEqual((Path(td) / "cover.png").read_bytes(), b"PNG-802")
            design = json.dumps(json.loads((Path(td) / "design.json").read_text(encoding="utf-8")),
                                ensure_ascii=False)
            self.assertIn("链接版标题", design)
            self.assertNotIn("旧版标题", design)
            self.assertNotIn("重传版标题", design)

        urls = [u for u, _ in platform.requests]
        for forbidden in (f"{SELFHOST}/api/assets/797", f"{SELFHOST}/api/assets/805",
                          f"{SELFHOST}/api/assets/810", f"{SELFHOST}/api/assets/830",
                          f"{SELFHOST}/api/projects/18/assets"):
            self.assertNotIn(forbidden, urls)

    def test_device_and_name_come_from_the_linked_upload(self):
        # 平台前端按 figmaPlatform ?? 'android' 归类；非插件上传的资产名不带「Figma · 」
        for platform, device in (("ios", "ios"), (None, "android")):
            with self.subTest(platform=platform):
                page = asset(802, "调查问卷-1（俄语）", platform,
                             "2026-10-25T00:00:00.000Z", page_layers("标题"))
                with tempfile.TemporaryDirectory() as td:
                    code, out = fetch(Path(td), FakePlatform(platform_routes([page])))
                    self.assertEqual(code, 0, out)
                    design = json.loads((Path(td) / "design.json").read_text(encoding="utf-8"))
                self.assertEqual((design["meta"]["device"], design["artboard"]["name"],
                                  out["design_name"]),
                                 (device, "调查问卷-1（俄语）", "调查问卷-1（俄语）"))


BIND = Path(__file__).resolve().parents[1] / "scripts" / "bind.py"


def bind_cli(*argv):
    proc = subprocess.run([sys.executable, str(BIND), *argv],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def outline(node):
    """(id, type, [子节点...]) —— 只看层级与类型。"""
    return (node["id"], node["type"], [outline(c) for c in node.get("layers", [])])


GROUPING = {"groups": [
    {"name": "页面", "node_ids": [ROOT]},
    {"name": "导航", "node_ids": ["1644:2066"]},
    {"name": "卡片", "node_ids": ["1653:3000"]},
]}


def required_assets(out_dir):
    """取数产物经 bind → enrich 后仍要补图的节点 id。"""
    design = str(out_dir / "design.json")
    grouping, bound, enriched = (out_dir / n for n in ("g.json", "b.json", "e.json"))
    grouping.write_text(json.dumps(GROUPING), encoding="utf-8")
    for argv in (("bind", "--design-json", design, "--grouping", str(grouping),
                  "--output", str(bound)),
                 ("enrich", "--bound-json", str(bound), "--design-json", design,
                  "--slices-json", str(out_dir / "slices.json"), "--output", str(enriched))):
        code, _, err = bind_cli(*argv)
        if code != 0:
            raise AssertionError(err)
    return [a["id"] for a in json.loads(enriched.read_text(encoding="utf-8"))
            .get("asset_required", [])]


class SelfhostDesignJsonTest(unittest.TestCase):
    """design.json 的契约就是 bind.py 能读出的结构与样式。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        new = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                    "2026-10-25T00:00:00.000Z", page_layers("新版标题"))
        code, out = fetch(self.dir, FakePlatform(platform_routes([new])))
        self.assertEqual(code, 0, out)
        self.design = str(self.dir / "design.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_prepare_sees_parent_tree_under_artboard(self):
        prepared = self.dir / "prepared.json"
        code, _, err = bind_cli("prepare", "--design-json", self.design, "--output", str(prepared))
        self.assertEqual(code, 0, err)
        out = json.loads(prepared.read_text(encoding="utf-8"))

        self.assertEqual(out["meta"]["artboard_name"], "调查问卷-1（俄语）")
        self.assertEqual(out["meta"]["artboard_frame"],
                         {"left": 0, "top": 0, "width": 390, "height": 844})
        self.assertEqual(out["total_nodes"], 6)
        self.assertEqual(outline(out["tree"]), (ROOT, "artboard", [
            ("1644:2066", "symbolInstence", [("I1644:2066;41:910", "textLayer", [])]),
            ("1653:3000", "groupLayer", [
                ("1653:3103", "symbolInstence", [("1653:3104", "shapeLayer", [])]),
            ]),
        ]))
        title = out["tree"]["layers"][0]["layers"][0]
        self.assertEqual((title["text"], title["position"], title["size"]),
                         ("新版标题", "52,50", "200x28"))

    def test_bind_extracts_styles_in_lanhu_units(self):
        grouping = self.dir / "grouping.json"
        grouping.write_text(json.dumps(GROUPING), encoding="utf-8")
        bound = self.dir / "bound.json"
        code, _, err = bind_cli("bind", "--design-json", self.design,
                                "--grouping", str(grouping), "--output", str(bound))
        self.assertEqual(code, 0, err)
        result = json.loads(bound.read_text(encoding="utf-8"))
        self.assertEqual((result["ok"], result["unbound_nodes"]), (True, 0))
        members = {m["id"]: m for c in result["components"] for m in c["members"]}

        nav = members["1644:2066"]
        self.assertEqual(nav["frame"], {"left": 0, "top": 44, "width": 390, "height": 44})
        self.assertEqual(nav["fills"], [{"type": "color", "value": "#FFFFFF"}])

        title = members["I1644:2066;41:910"]
        self.assertNotIn("fills", title)
        self.assertEqual(title["text"]["value"], "新版标题")
        keys = ("font", "size", "weight", "align", "line_height", "color", "letter_spacing")
        self.assertEqual([{k: s[k] for k in keys} for s in title["text"]["spans"]], [{
            "font": "SF Pro", "size": 18, "weight": 700, "align": "left",
            "line_height": 28, "color": "#121212", "letter_spacing": 1.8,
        }])

        card = members["1653:3000"]
        self.assertEqual(card["radius"],
                         {"topLeft": 12, "topRight": 8, "bottomRight": 4, "bottomLeft": 0})
        self.assertEqual(card["fills"], [{"type": "color", "value": "rgba(51,123,85,0.06)"}])
        self.assertEqual([(b["width"], b["color"]) for b in card["borders"]], [(1, "#E5E5E5")])

        checkbox = members["1653:3103"]
        self.assertNotIn("fills", checkbox)
        self.assertNotIn("radius", checkbox)
        self.assertEqual(members["1653:3104"]["fills"], [{"type": "color", "value": "#D9456D"}])

    def test_boolean_operation_is_marked_as_needing_an_asset(self):
        # 蓝湖带 booleanOperation 的形状会被 enrich 标为需切图，平台的 BOOLEAN_OPERATION 也要
        icon = layer("1653:3300", "1653:3000", "图标", "BOOLEAN_OPERATION", 300, 140, 20, 20,
                     fillColor="#121212", fillOpacity=1)
        page = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                     "2026-10-25T00:00:00.000Z", page_layers("标题") + [icon])
        out_dir = self.dir / "bool"
        code, out = fetch(out_dir, FakePlatform(platform_routes([page])))
        self.assertEqual(code, 0, out)
        self.assertIn("1653:3300", required_assets(out_dir))


class SelfhostSlicesTest(unittest.TestCase):
    def test_slices_attach_to_layers_and_land_locally(self):
        # 与「选择框」同位置同尺寸的内层 frame 排在前面，按列表顺序取第一个就会挂错
        layers = [layer("1653:3105", "1653:3103", "Frame 1", "FRAME", 40, 140, 24, 24)]
        layers += page_layers("新版标题")
        full = [slice_(802, 7000 + i, f"调查问卷-1（俄语） · PNG @{i}x", 0, 0, 390, 844)
                for i in (1, 2, 3)]
        box = [slice_(802, 7010 + i, f"选择框 · PNG @{i}x", 40, 140, 24, 24) for i in (1, 2, 3)]
        orphan = [slice_(802, 7020 + i, f"选择框 · PNG @{i}x 2", 40, 400, 24, 24)
                  for i in (1, 2, 3)]
        new = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                    "2026-10-25T00:00:00.000Z", layers, full + box + orphan)
        served = {f"{SELFHOST}{s['preview']}": f"S-{s['id']}".encode() for s in box + orphan}
        platform = FakePlatform(platform_routes([new], served))

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            code, out = fetch(tmp, platform)
            self.assertEqual(code, 0, out)
            slices = json.loads((tmp / "slices.json").read_text(encoding="utf-8"))["slices"]

            self.assertEqual([(s["id"], s["name"], s["frame"]) for s in slices], [
                ("1653:3103", "选择框", {"left": 40, "top": 140, "width": 24, "height": 24}),
                (None, "选择框", {"left": 40, "top": 400, "width": 24, "height": 24}),
            ])
            for s, largest_id in zip(slices, (7013, 7023)):
                self.assertEqual(s["logical_size"], {"width": 24, "height": 24})
                # 只落最大倍率；远端地址要 cookie，不交给下游
                self.assertEqual((tmp / s["local_png"]).read_bytes(),
                                 f"S-{largest_id}".encode())
                self.assertEqual((s["download_url"], s["scale_urls"]), (None, None))

            self.assertEqual((out["slices_total"], out["slices_downloaded"]), (2, 2))
            self.assertEqual(len(out["warnings"]), 1)
            self.assertIn("选择框", out["warnings"][0])

        urls = [u for u, _ in platform.requests]
        for s in full + box[:2] + orphan[:2]:
            self.assertNotIn(f"{SELFHOST}{s['preview']}", urls)

    def test_two_slices_never_share_one_layer(self):
        # blueprint 按 id 建索引，同 id 的切图会互相覆盖、取错图：宁可不挂并告警
        same_box = [slice_(802, 7031, "选择框 · PNG @2x", 40, 140, 24, 24),
                    slice_(802, 7032, "其他 · PNG @2x", 40, 140, 24, 24)]
        page = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                     "2026-10-25T00:00:00.000Z", page_layers("标题"), same_box)
        served = {f"{SELFHOST}{s['preview']}": b"S" for s in same_box}
        with tempfile.TemporaryDirectory() as td:
            code, out = fetch(Path(td), FakePlatform(platform_routes([page], served)))
            self.assertEqual(code, 0, out)
            slices = json.loads((Path(td) / "slices.json").read_text(encoding="utf-8"))["slices"]
            # 没挂上切图的图层不能标成已导出，否则 enrich 不再要求补图，页面静默缺图
            self.assertIn("1653:3103", required_assets(Path(td)))
        self.assertEqual([(s["id"], s["name"]) for s in slices], [(None, "选择框"), (None, "其他")])
        self.assertTrue(out.get("warnings"))

    def test_sliced_layer_is_not_reported_as_missing_an_asset(self):
        # 蓝湖导出过切图的节点带 image，enrich 不再要求补图；自建平台挂上切图的图层也一样
        box = [slice_(802, 7010 + i, f"选择框 · PNG @{i}x", 40, 140, 24, 24) for i in (1, 2, 3)]
        icon = [layer("1653:3200", "1653:3000", "图标", "INSTANCE", 300, 140, 20, 20),
                layer("1653:3201", "1653:3200", "形", "VECTOR", 302, 142, 16, 16)]
        page = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                     "2026-10-25T00:00:00.000Z", page_layers("标题") + icon, box)
        platform = FakePlatform(platform_routes([page], {f"{SELFHOST}{box[2]['preview']}": b"S"}))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            code, out = fetch(tmp / "out", platform)
            self.assertEqual(code, 0, out)
            required = required_assets(tmp / "out")
        # 没切图、不含文字的图标实例仍要补图
        self.assertEqual(required, ["1653:3200"])

    def test_full_screen_slice_is_kept_unless_it_is_the_artboard_export(self):
        layers = page_layers("标题") + [
            layer("1653:3900", ROOT, "背景", "RECTANGLE", 0, 0, 390, 844)]
        bg = slice_(802, 7100, "背景 · PNG @2x", 0, 0, 390, 844)
        board = slice_(802, 7101, "调查问卷-1（俄语） · PNG @2x", 0, 0, 390, 844)
        # 与画板同名但不在整画板位置：是普通切图
        card = slice_(802, 7102, "调查问卷-1（俄语） · PNG @2x", 16, 120, 358, 200)
        new = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                    "2026-10-25T00:00:00.000Z", layers, [bg, board, card])
        platform = FakePlatform(platform_routes([new], {f"{SELFHOST}{bg['preview']}": b"BG",
                                                        f"{SELFHOST}{card['preview']}": b"CARD"}))

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            code, out = fetch(tmp, platform)
            self.assertEqual(code, 0, out)
            slices = json.loads((tmp / "slices.json").read_text(encoding="utf-8"))["slices"]
            self.assertEqual([(s["id"], s["name"]) for s in slices],
                             [("1653:3900", "背景"), ("1653:3000", "调查问卷-1（俄语）")])
            self.assertEqual((tmp / slices[0]["local_png"]).read_bytes(), b"BG")
        self.assertNotIn(f"{SELFHOST}{board['preview']}", [u for u, _ in platform.requests])


class SelfhostCoverTest(unittest.TestCase):
    def test_cover_download_failure_is_a_warning_like_lanhu(self):
        page = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                     "2026-10-25T00:00:00.000Z", page_layers("标题"))
        routes = platform_routes([page])
        del routes[f"{SELFHOST}/api/assets/802"]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            code, out = fetch(tmp, FakePlatform(routes))
            self.assertEqual(code, 0, out)
            self.assertTrue(out["ok"])
            self.assertIsNone(out["cover_image"])
            self.assertEqual(len(out["warnings"]), 1)
            self.assertIn("cover", out["warnings"][0])
            self.assertFalse((tmp / "cover.png").exists())
            self.assertTrue((tmp / "design.json").exists())
            self.assertTrue((tmp / "slices.json").exists())


class SelfhostCookieTest(unittest.TestCase):
    """cookie 取值顺序：--cookie → $SELFHOST_COOKIE → ~/.config/icp/selfhost.env。"""

    def fetch_with(self, env_cookie=None, cli_cookie=None, file_text=None):
        page = asset(802, "Figma · 调查问卷-1（俄语）", "android",
                     "2026-10-23T07:51:13.444Z", page_layers("标题"))
        platform = FakePlatform(platform_routes([page]))
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as out:
            if file_text is not None:
                f = Path(home) / ".config" / "icp" / "selfhost.env"
                f.parent.mkdir(parents=True)
                f.write_text(file_text, encoding="utf-8")
            with patch.dict(os.environ, {"HOME": home}, clear=False):
                os.environ.pop("SELFHOST_COOKIE", None)
                if env_cookie is not None:
                    os.environ["SELFHOST_COOKIE"] = env_cookie
                code, result = fetch(Path(out) / "o", platform, cookie=cli_cookie)
        return code, result, platform

    def test_cookie_falls_back_to_config_file(self):
        code, result, platform = self.fetch_with(file_text=(
            "# 自建设计平台\nOTHER=x\nSELFHOST_COOKIE=\"sess=file; uid=7\"\n"))
        self.assertEqual(code, 0, result)
        self.assertTrue(platform.requests)
        self.assertEqual({c for _, c in platform.requests}, {"sess=file; uid=7"})

    def test_cli_beats_env_beats_file(self):
        file_text = "SELFHOST_COOKIE=sess=file\n"
        for kw, expected in (({"cli_cookie": "sess=cli", "env_cookie": "sess=env"}, "sess=cli"),
                             ({"env_cookie": "sess=env"}, "sess=env")):
            with self.subTest(expected=expected):
                code, result, platform = self.fetch_with(file_text=file_text, **kw)
                self.assertEqual(code, 0, result)
                self.assertEqual({c for _, c in platform.requests}, {expected})


class SelfhostFetchFailureTest(unittest.TestCase):
    """失败即停：报对应错误、不落任何产物、不下载任何设计图。"""

    def assert_fails(self, err_type, assets, ref=REF, cookie=COOKIE, routes=None):
        platform = FakePlatform(routes if routes is not None else platform_routes(assets))
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            # HOME 指向空目录：用户本机的 ~/.config/icp/selfhost.env 不能影响结果
            with patch.dict(os.environ, {"HOME": td}, clear=False):
                os.environ.pop("SELFHOST_COOKIE", None)
                code, out = fetch(out_dir, platform, ref=ref, cookie=cookie)
            self.assertNotEqual(code, 0)
            self.assertEqual(out["ok"], False)
            self.assertEqual([e["type"] for e in out["errors"]], [err_type])
            self.assertFalse(out_dir.exists(), "失败时不能写出任何产物")
        downloads = [u for u, _ in platform.requests if "/api/assets/" in u]
        self.assertEqual(downloads, [])
        return platform, out

    def page(self, aid):
        return asset(aid, "Figma · 调查问卷-1（俄语）", "android",
                     "2026-10-25T00:00:00.000Z", page_layers("标题"))

    def test_no_cookie_sends_no_request(self):
        platform, out = self.assert_fails("no_cookie", [self.page(802)], cookie=None)
        self.assertEqual(platform.requests, [])
        self.assertIn("~/.config/icp/selfhost.env", out["errors"][0]["detail"])

    def test_unknown_project(self):
        # 平台对不存在/无权限的项目，assets 接口一律回 403：要报 project_not_found 而不是接口失败
        url = f"{SELFHOST}/api/projects/99/assets"
        routes = platform_routes([self.page(802)])
        routes[url] = self.http_error(url, 403)
        self.assert_fails("project_not_found", [], routes=routes,
                          ref=f"{SELFHOST}/?project=99&design=802")

    def test_unknown_design(self):
        # 与平台前端打开链接一致：只认有 preview 的 UI 设计图
        prototype = dict(self.page(802), kind="axure")
        hidden = dict(self.page(802), preview=None)
        for label, assets in (("missing", [self.page(801)]), ("prototype", [prototype]),
                              ("no_preview", [hidden])):
            with self.subTest(label):
                self.assert_fails("design_not_found", assets)

    def test_unusable_layer_data(self):
        broken = self.page(802)
        broken["layers"][0]["parentId"] = "9999:1"  # 两个找不到的父 id
        # 链接的那次上传坏了：报错让设计师重传，不能悄悄换成同画板的另一版
        empty = asset(802, "Figma · 调查问卷-1（俄语）", "android", "2026-10-25", [])
        # parentId 互相成环、挂不到画板上的图层不能被悄悄丢掉
        cyclic = self.page(802)
        cyclic["layers"] += [layer("9:1", "9:2", "A", "RECTANGLE", 0, 0, 1, 1),
                             layer("9:2", "9:1", "B", "RECTANGLE", 0, 0, 1, 1)]
        for label, assets in (("broken", [broken]), ("empty", [self.page(801), empty]),
                              ("cyclic", [cyclic])):
            with self.subTest(label):
                self.assert_fails("bad_design_data", assets)

    def test_malformed_platform_data(self):
        # 结构不对也只能有一行错误 JSON，且切图问题不能在 design.json 落盘后才暴露
        no_x = self.page(802)
        del no_x["layers"][2]["x"]
        null_opacity = self.page(802)
        null_opacity["layers"][0]["fillOpacity"] = None
        slice_no_preview = self.page(802)
        slice_no_preview["slices"] = [
            {"id": 9, "name": "图标 · PNG @2x", "x": 1, "y": 2, "width": 3, "height": 4}]
        not_an_object = platform_routes([self.page(802)])
        not_an_object[f"{SELFHOST}/api/projects"] = []
        cases = [("no_x", platform_routes([no_x])),
                 ("null_opacity", platform_routes([null_opacity])),
                 ("slice_no_preview", platform_routes([slice_no_preview])),
                 ("not_an_object", not_an_object)]
        # 服务端给的路径/id 不能把 cookie 带到别的主机，也不能写出 out-dir
        for label, field, value in (("slice_preview_null", "preview", None),
                                    ("slice_preview_other_host", "preview", "@evil.example/x"),
                                    ("slice_id_traversal", "id", "../../evil"),
                                    ("slice_id_infinite", "id", float("inf")),
                                    ("slice_id_fraction", "id", 7.9),
                                    ("slice_id_bool", "id", True)):
            page = self.page(802)
            s = slice_(802, 9, "图标 · PNG @2x", 1, 2, 3, 4)
            s[field] = value
            page["slices"] = [s]
            cases.append((label, platform_routes([page])))
        cover_other_host = self.page(802)
        cover_other_host["preview"] = "//evil.example/x"
        cases.append(("cover_other_host", platform_routes([cover_other_host])))
        for label, routes in cases:
            with self.subTest(label):
                platform, _ = self.assert_fails("bad_design_data", [], routes=routes)
                for url, _ in platform.requests:
                    self.assertTrue(url.startswith(f"{SELFHOST}/api/"), url)

    def test_rejected_cookie(self):
        url = f"{SELFHOST}/api/projects"
        routes = platform_routes([self.page(802)])
        routes[url] = self.http_error(url, 401)
        _, out = self.assert_fails("cookie_rejected", [], routes=routes)
        self.assertIn("~/.config/icp/selfhost.env", out["errors"][0]["detail"])

    def test_platform_request_failure(self):
        self.assert_fails("request_failed", [], routes={})
        # 只有 401 是 cookie 问题，其它 HTTP 错误照常报接口失败
        url = f"{SELFHOST}/api/projects"
        self.assert_fails("request_failed", [], routes={url: self.http_error(url, 500)})

    def http_error(self, url, code):
        err = urllib.error.HTTPError(url, code, "error", None, None)
        self.addCleanup(err.close)
        return err


if __name__ == "__main__":
    unittest.main()
