import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate.py"


def run(*argv, expect=0):
    p = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True)
    out = json.loads(p.stdout.strip()) if p.stdout.strip() else {}
    if expect is not None:
        assert p.returncode == expect, f"{argv}\nrc={p.returncode}\n{p.stdout}\n{p.stderr}"
    return p.returncode, out


def write_json(tmp, name, data):
    path = tmp / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def make_spec(tmp):
    return write_json(tmp, "spec.json", {
        "components": [
            {"name": "导航栏", "role": "navigation", "members": []},
            {"name": "表单区", "role": "form", "members": []},
            {"name": "底部按钮", "role": "action", "members": []},
        ]
    })


def make_good_binding(tmp):
    real_file = tmp / "nav_bar.dart"
    real_file.write_text("class AppNavBar {}", encoding="utf-8")
    return write_json(tmp, "binding.json", {
        "platform": {"name": "flutter", "framework": "material"},
        "apis": [{"endpoint": "/auth/login", "method": "POST"}],
        "components": [
            {"group_name": "导航栏", "component_name": "AppNavBar",
             "component_type": "existing_shared", "source_path": str(real_file),
             "params": ["title"], "affected": None},
            {"group_name": "表单区", "component_name": "LoginForm",
             "component_type": "new", "source_path": None,
             "params": [], "affected": None},
            {"group_name": "底部按钮", "component_name": "SubmitButton",
             "component_type": "platform_builtin", "source_path": None,
             "params": [], "affected": None},
        ],
        "interactions": [
            {"id": "ix_1", "component": "LoginForm", "type": "behavior",
             "condition": None, "state": "focused",
             "trigger": "点击输入框", "behavior": "获得焦点",
             "result": "显示键盘", "api": None, "triggers": ["ix_2"]},
            {"id": "ix_2", "component": "SubmitButton", "type": "data",
             "condition": "表单填写完整", "state": "submitting",
             "trigger": "点击提交", "behavior": "按钮禁用",
             "result": "提交登录", "api": "/auth/login", "triggers": []},
        ],
    })


class TestCheckBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.spec = make_spec(self.tmp)

    def test_good_binding_passes(self):
        binding = make_good_binding(self.tmp)
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding)
        self.assertTrue(out["ok"])

    def test_unbound_group(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("unbound_group", types)

    def test_invalid_type(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "magic", "source_path": None, "params": [], "affected": None},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("invalid_type", types)

    def test_missing_source_existing_shared(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "existing_shared", "source_path": "/no/such/file.dart",
                 "params": ["x"], "affected": None},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("missing_source", types)

    def test_existing_shared_null_source(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "existing_shared", "source_path": None,
                 "params": ["x"], "affected": None},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("missing_source", types)

    def test_invalid_affected_on_non_extract(self):
        real = self.tmp / "x.dart"
        real.write_text("x", encoding="utf-8")
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "new", "source_path": None, "params": [],
                 "affected": [{"name": "X", "source_path": str(real)}]},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("invalid_affected", types)

    def test_missing_affected_source(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "extract_shared", "source_path": None,
                 "params": ["x"],
                 "affected": [{"name": "Old", "source_path": "/no/such.dart"}]},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("missing_affected_source", types)

    def test_affected_empty_source_path(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "extract_shared", "source_path": None,
                 "params": ["x"],
                 "affected": [{"name": "Old", "source_path": ""}]},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("missing_affected_source", types)

    def test_empty_params_shared(self):
        real = self.tmp / "nav.dart"
        real.write_text("x", encoding="utf-8")
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "existing_shared", "source_path": str(real),
                 "params": [], "affected": None},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("empty_params", types)

    def test_extra_group_warning(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "Nav",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "幽灵组", "component_name": "Ghost",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding)
        self.assertTrue(out["ok"])
        warns = {w["type"] for w in out.get("warnings", [])}
        self.assertIn("extra_group", warns)

    def test_extract_shared_good(self):
        affected_file = self.tmp / "old.dart"
        affected_file.write_text("x", encoding="utf-8")
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "导航栏", "component_name": "SharedNav",
                 "component_type": "extract_shared", "source_path": None,
                 "params": ["style"],
                 "affected": [{"name": "OldNav", "source_path": str(affected_file)}]},
                {"group_name": "表单区", "component_name": "F",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
                {"group_name": "底部按钮", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": [], "affected": None},
            ]
        })
        rc, out = run("check-binding", "--component-spec", self.spec, "--binding", binding)
        self.assertTrue(out["ok"])


class TestCheckInteractions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_good_interactions_pass(self):
        binding = make_good_binding(self.tmp)
        rc, out = run("check-interactions", "--binding", binding)
        self.assertTrue(out["ok"])

    def test_incomplete_interaction(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "", "trigger": "click",
                 "behavior": "show", "result": "done", "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        err = out["errors"][0]
        self.assertEqual(err["type"], "incomplete_interaction")
        self.assertEqual(err["missing_field"], "state")

    def test_missing_api_on_data_type(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "data",
                 "condition": None, "state": "loading", "trigger": "click",
                 "behavior": "show spinner", "result": "fetch data",
                 "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("missing_api", types)

    def test_unknown_api(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [{"endpoint": "/real", "method": "GET"}],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "data",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": "/fake", "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("unknown_api", types)

    def test_broken_trigger(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": None, "triggers": ["ix_99"]},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("broken_trigger", types)

    def test_unknown_component(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "Ghost", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("unknown_component", types)

    def test_idle_component_warning(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [
                {"group_name": "A", "component_name": "A",
                 "component_type": "new", "source_path": None, "params": []},
                {"group_name": "B", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": []},
            ],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding)
        self.assertTrue(out["ok"])
        warns = {w["type"] for w in out.get("warnings", [])}
        self.assertIn("idle_component", warns)

    def test_no_orphan_warning(self):
        binding = make_good_binding(self.tmp)
        rc, out = run("check-interactions", "--binding", binding)
        warn_types = {w["type"] for w in out.get("warnings", [])}
        self.assertNotIn("orphan_interaction", warn_types)

    def test_duplicate_id(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s1", "trigger": "t1",
                 "behavior": "b1", "result": "r1", "api": None, "triggers": []},
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s2", "trigger": "t2",
                 "behavior": "b2", "result": "r2", "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("duplicate_id", types)

    def test_missing_id(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"component": "A", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r", "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        types = {e["type"] for e in out["errors"]}
        self.assertIn("missing_id", types)

    def test_forward_trigger_ref_not_broken(self):
        """ix_1 triggers ix_2, but ix_2 appears after ix_1 — should NOT report broken_trigger."""
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s1", "trigger": "t1",
                 "behavior": "b1", "result": "r1", "api": None, "triggers": ["ix_2"]},
                {"id": "ix_2", "component": "A", "type": "behavior",
                 "condition": None, "state": "s2", "trigger": "t2",
                 "behavior": "b2", "result": "r2", "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding)
        self.assertTrue(out["ok"])

    def test_missing_component_field(self):
        binding = write_json(self.tmp, "b.json", {
            "components": [{"group_name": "A", "component_name": "A",
                            "component_type": "new", "source_path": None, "params": []}],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding, expect=1)
        errs = [e for e in out["errors"] if e.get("missing_field") == "component"]
        self.assertEqual(len(errs), 1)



    def test_idle_non_interactive_role_is_silent(self):
        """role 已知且非交互(decoration/content)的空闲组件不该产出任何条目。"""
        spec = write_json(self.tmp, "spec_roles.json", {
            "components": [
                {"name": "A", "role": "action"},
                {"name": "B", "role": "decoration"},
                {"name": "C", "role": "content"},
            ],
        })
        binding = write_json(self.tmp, "b_roles.json", {
            "components": [
                {"group_name": "A", "component_name": "A",
                 "component_type": "new", "source_path": None, "params": []},
                {"group_name": "B", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": []},
                {"group_name": "C", "component_name": "C",
                 "component_type": "new", "source_path": None, "params": []},
            ],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding,
                      "--component-spec", spec)
        self.assertTrue(out["ok"], out)
        self.assertEqual([], out.get("warnings", []))

    def test_idle_interactive_role_is_error(self):
        """role 是 action/form 的空闲组件必须报错，不能降级成 warning。"""
        spec = write_json(self.tmp, "spec_act.json", {
            "components": [
                {"name": "A", "role": "content"},
                {"name": "B", "role": "action"},
            ],
        })
        binding = write_json(self.tmp, "b_act.json", {
            "components": [
                {"group_name": "A", "component_name": "A",
                 "component_type": "new", "source_path": None, "params": []},
                {"group_name": "B", "component_name": "B",
                 "component_type": "new", "source_path": None, "params": []},
            ],
            "apis": [],
            "interactions": [
                {"id": "ix_1", "component": "A", "type": "behavior",
                 "condition": None, "state": "s", "trigger": "t",
                 "behavior": "b", "result": "r",
                 "api": None, "triggers": []},
            ],
        })
        rc, out = run("check-interactions", "--binding", binding,
                      "--component-spec", spec, expect=1)
        errs = {(e["type"], e["component_name"]) for e in out["errors"]}
        self.assertIn(("idle_interactive_component", "B"), errs)


if __name__ == "__main__":
    unittest.main()
