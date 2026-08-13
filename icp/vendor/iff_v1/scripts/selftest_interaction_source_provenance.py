#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "check_interaction_completeness.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run(contract: Path, row: Path, report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--contract", str(contract), "--row", str(row), "--out", str(report)],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-interaction-provenance-") as raw_tmp:
        root = Path(raw_tmp)
        row = root / "row.json"
        contract = root / "interaction_contract.json"
        report = root / "report.json"

        interaction = "点击 Apply 后请求接口\n失败时展示错误"
        write_json(row, {"interaction": interaction})
        write_json(contract, {"source": "", "rules": [], "ignoredItems": []})
        mismatch = run(contract, row, report)
        assert mismatch.returncode == 1, mismatch.stdout + mismatch.stderr
        assert json.loads(report.read_text(encoding="utf-8"))["sourceMatch"] is False

        write_json(contract, {"source": interaction, "rules": [], "ignoredItems": []})
        empty_rules = run(contract, row, report)
        assert empty_rules.returncode == 1, empty_rules.stdout + empty_rules.stderr
        assert "zero rules" in empty_rules.stdout

        write_json(contract, {"source": interaction, "rules": [{"id": "apply"}], "ignoredItems": []})
        complete = run(contract, row, report)
        assert complete.returncode == 0, complete.stdout + complete.stderr

        write_json(row, {"interaction": "无"})
        write_json(contract, {"source": "无", "rules": [], "ignoredItems": []})
        sentinel = run(contract, row, report)
        assert sentinel.returncode == 0, sentinel.stdout + sentinel.stderr

    print("PASS: interaction completeness rejects source loss and false-green empty contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
