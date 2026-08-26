"""Tests for enrich — textLayer 守卫: 后代含 textLayer 的节点不附加切片。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from bind import _has_text_descendant, build_index


def _make_design(layers):
    return {"artboard": {"id": "root", "type": "artboard", "layers": layers}}


def _make_node(nid, ntype, children=None):
    n = {"id": nid, "type": ntype, "name": nid}
    if children:
        n["layers"] = children
    return n


class TestHasTextDescendant(unittest.TestCase):

    def test_direct_text_child(self):
        design = _make_design([
            _make_node("g1", "symbolInstence", [
                _make_node("t1", "textLayer"),
            ]),
        ])
        idx, _ = build_index(design["artboard"])
        self.assertTrue(_has_text_descendant("g1", idx))

    def test_nested_text_grandchild(self):
        design = _make_design([
            _make_node("g1", "symbolInstence", [
                _make_node("g2", "symbolInstence", [
                    _make_node("t1", "textLayer"),
                ]),
            ]),
        ])
        idx, _ = build_index(design["artboard"])
        self.assertTrue(_has_text_descendant("g1", idx))

    def test_no_text_descendants(self):
        design = _make_design([
            _make_node("g1", "symbolInstence", [
                _make_node("s1", "shapeLayer"),
                _make_node("s2", "shapeLayer"),
            ]),
        ])
        idx, _ = build_index(design["artboard"])
        self.assertFalse(_has_text_descendant("g1", idx))

    def test_empty_node(self):
        idx = {}
        self.assertFalse(_has_text_descendant("missing", idx))

    def test_leaf_text_node(self):
        design = _make_design([_make_node("t1", "textLayer")])
        idx, _ = build_index(design["artboard"])
        self.assertFalse(_has_text_descendant("t1", idx))


SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "bind.py")


class TestEnrichSliceGuard(unittest.TestCase):

    def _run_enrich(self, bound, slices, design):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            bp = td / "bound.json"
            bp.write_text(json.dumps(bound))
            sp = td / "slices.json"
            sp.write_text(json.dumps(slices))
            dp = td / "design.json"
            dp.write_text(json.dumps(design))
            op = td / "enriched.json"
            r = subprocess.run(
                [sys.executable, SCRIPT, "enrich",
                 "--bound-json", str(bp), "--slices-json", str(sp),
                 "--design-json", str(dp), "--output", str(op)],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(op.read_text())

    def test_slice_skipped_when_text_descendant(self):
        bound = {"components": [{"name": "header", "members": [
            {"id": "g1", "type": "symbolInstence", "name": "Header-bg"},
        ]}]}
        slices = {"slices": [
            {"id": "g1", "name": "Header-bg", "scale_urls": {"2x": "http://x"},
             "svg_url": None, "logical_size": {"width": 390, "height": 288}},
        ]}
        design = _make_design([
            _make_node("g1", "symbolInstence", [
                _make_node("t1", "textLayer"),
                _make_node("s1", "shapeLayer"),
            ]),
        ])
        result = self._run_enrich(bound, slices, design)
        member = result["components"][0]["members"][0]
        self.assertNotIn("scale_urls", member)

    def test_slice_attached_when_no_text(self):
        bound = {"components": [{"name": "icon", "members": [
            {"id": "g2", "type": "symbolInstence", "name": "Icon"},
        ]}]}
        slices = {"slices": [
            {"id": "g2", "name": "Icon", "scale_urls": {"2x": "http://y"},
             "svg_url": None, "logical_size": {"width": 24, "height": 24}},
        ]}
        design = _make_design([
            _make_node("g2", "symbolInstence", [
                _make_node("s1", "shapeLayer"),
            ]),
        ])
        result = self._run_enrich(bound, slices, design)
        member = result["components"][0]["members"][0]
        self.assertIn("scale_urls", member)
        self.assertEqual(member["scale_urls"]["2x"], "http://y")


if __name__ == "__main__":
    unittest.main()
