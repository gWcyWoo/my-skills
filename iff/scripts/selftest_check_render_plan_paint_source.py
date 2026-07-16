#!/usr/bin/env python3
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    script = Path(__file__).with_name("check_render_plan.py")
    with tempfile.TemporaryDirectory() as td:
        plan = Path(td) / "render_plan.json"
        payload = {
            "nodes": {
                "logo": {
                    "implementation": "shape",
                    "bbox": [0, 0, 74, 74],
                    "required": True,
                    "renderMode": "absolute_positioned",
                    "widgetTraceRequired": True,
                    "fills": [],
                    "solidFills": [],
                    "gradientFills": [],
                    "imageFills": [],
                    "border": [],
                    "shadow": [],
                    "effects": [],
                    "asset": None,
                }
            }
        }
        plan.write_text(json.dumps(payload), encoding="utf-8")
        missing = subprocess.run(["python3", str(script), str(plan)], text=True, capture_output=True)
        assert missing.returncode != 0, missing.stdout
        assert "required visible shape has no paint source" in missing.stderr, missing.stderr

        payload["nodes"]["logo"]["fills"] = ["#66DD77"]
        plan.write_text(json.dumps(payload), encoding="utf-8")
        painted = subprocess.run(["python3", str(script), str(plan)], text=True, capture_output=True)
        assert painted.returncode == 0, painted.stderr
    print("OK: required visible shapes cannot pass without a deterministic paint source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
