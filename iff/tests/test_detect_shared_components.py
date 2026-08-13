from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "detect_shared_components.py"


def write_design(
    spec: Path,
    group_name: str,
    *,
    title_text: str = "Title",
    with_subtitle: bool = False,
) -> None:
    spec.mkdir(parents=True)
    children = ["title", "subtitle"] if with_subtitle else ["title"]
    nodes = [
        {
            "id": "root",
            "name": group_name,
            "type": "FRAME",
            "bbox": [0, 0, 320, 72 if with_subtitle else 56],
            "children": children,
        },
        {
            "id": "title",
            "name": "Title",
            "type": "TEXT",
            "bbox": [16, 16, 100, 24],
            "children": [],
            "text": title_text,
        },
    ]
    if with_subtitle:
        nodes.append(
            {
                "id": "subtitle",
                "name": "Subtitle",
                "type": "TEXT",
                "bbox": [16, 44, 160, 16],
                "children": [],
                "text": "Optional subtitle",
            }
        )
    (spec / "scene.json").write_text(
        json.dumps({"nodes": nodes}),
        encoding="utf-8",
    )
    (spec / "groups.json").write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "id": "group-root",
                        "node": "root",
                        "kind": "region",
                        "bbox": [0, 0, 320, 56],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class DetectSharedComponentsTest(unittest.TestCase):
    def test_optional_leaf_difference_is_reported_as_related_candidate_not_auto_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compact = root / "compact"
            expanded = root / "expanded"
            write_design(compact, "Header", with_subtitle=False)
            write_design(expanded, "Header", with_subtitle=True)
            registry = root / "registry.json"
            registry.write_text('{"version": 2, "components": {}}', encoding="utf-8")
            out = root / "batch.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dirs",
                    str(compact),
                    str(expanded),
                    "--registry",
                    str(registry),
                    "--kinds",
                    "region",
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            components = json.loads(out.read_text(encoding="utf-8"))["components"]
            self.assertEqual(2, len(components))
            self.assertEqual({"candidate"}, {component["status"] for component in components})
            signatures = {component["signature"] for component in components}
            for component in components:
                self.assertEqual(signatures - {component["signature"]}, set(component["related_signatures"]))

    def test_structural_match_requires_semantic_decision_before_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            write_design(first, "Navigation Header", title_text="Home")
            write_design(second, "Destructive Warning", title_text="Delete account")
            registry = root / "registry.json"
            registry.write_text('{"version": 1, "components": {}}', encoding="utf-8")
            out = root / "batch.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dirs",
                    str(first),
                    str(second),
                    "--registry",
                    str(registry),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            components = json.loads(out.read_text(encoding="utf-8"))["components"]
            self.assertEqual(1, len(components))
            self.assertEqual("candidate", components[0]["status"])
            self.assertEqual(
                {"required": True, "reason": "structural_match_only"},
                components[0]["model_decision"],
            )
            self.assertEqual(
                [
                    {
                        "index": 1,
                        "type": "TEXT",
                        "fields": {"text": ["Delete account", "Home"]},
                    }
                ],
                components[0]["variations"],
            )

    def test_confirmed_cross_file_source_alias_reuses_registered_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "copied-file"
            write_design(spec, "Copied Header")
            empty_registry = root / "empty.json"
            empty_registry.write_text('{"version": 2, "components": {}}', encoding="utf-8")
            discovery = root / "discovery.json"
            first = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dirs",
                    str(spec),
                    "--registry",
                    str(empty_registry),
                    "--kinds",
                    "region",
                    "--out",
                    str(discovery),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            signature = json.loads(discovery.read_text(encoding="utf-8"))["components"][0]["signature"]

            registry = root / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:canonical-header": {
                                "family_id": "app_header",
                                "name": "AppHeader",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "source_aliases": [signature],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            resolved = root / "resolved.json"

            second = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dirs",
                    str(spec),
                    "--registry",
                    str(registry),
                    "--kinds",
                    "region",
                    "--out",
                    str(resolved),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            component = json.loads(resolved.read_text(encoding="utf-8"))["components"][0]
            self.assertEqual("reuse", component["status"])
            self.assertEqual("app_header", component["widget"]["family_id"])

    def test_role_mapping_survives_optional_nodes_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "header-with-subtitle"
            write_design(spec, "Header", with_subtitle=True)
            empty_registry = root / "empty.json"
            empty_registry.write_text('{"version": 2, "components": {}}', encoding="utf-8")
            discovery = root / "discovery.json"
            first = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dirs",
                    str(spec),
                    "--registry",
                    str(empty_registry),
                    "--kinds",
                    "region",
                    "--out",
                    str(discovery),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            signature = json.loads(discovery.read_text(encoding="utf-8"))["components"][0]["signature"]

            registry = root / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "components": {
                            "componentId:header": {
                                "family_id": "app_header",
                                "name": "AppHeader",
                                "widget_path": "lib/shared/components/app_header.dart",
                                "canonical_nodes": ["canonical-root", "canonical-title"],
                                "source_aliases": [signature],
                                "node_role_nodes": {
                                    "container": "canonical-root",
                                    "title": "canonical-title",
                                },
                                "alias_role_indices": {
                                    signature: {"container": 0, "title": 1}
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            resolved = root / "resolved.json"

            second = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--spec-dirs",
                    str(spec),
                    "--registry",
                    str(registry),
                    "--kinds",
                    "region",
                    "--out",
                    str(resolved),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            row = json.loads(resolved.read_text(encoding="utf-8"))["components"][0]["rows"][0]
            self.assertEqual(
                {"root": "canonical-root", "title": "canonical-title"},
                row["node_map"],
            )


if __name__ == "__main__":
    unittest.main()
