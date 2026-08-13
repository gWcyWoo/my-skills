#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().parent / "csv_row_status.py"
SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def fixture(*rows: bytes) -> bytes:
    header = "编号,标题,交互描述,状态,error\r\n".encode()
    return b"\xef\xbb\xbf" + header + b"\r\n".join(rows) + b"\r\n"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="iff-csv-row-status-") as raw_tmp:
        root = Path(raw_tmp)
        csv_path = root / "test.csv"
        original = fixture('1,首页,"第一行\n第二行","error",'.encode())
        csv_path.write_bytes(original)

        inspected = run("inspect", "--csv", str(csv_path), "--title", "首页")
        assert inspected.returncode == 0, inspected.stderr
        inspection = json.loads(inspected.stdout)
        assert inspection["format"] == {
            "encoding": "UTF-8",
            "bom": True,
            "delimiter": ",",
            "lineEndings": {"crlf": 2, "lf": 1, "cr": 0},
        }, inspection
        assert inspection["columns"] == {"title": "标题", "status": "状态"}, inspection
        assert inspection["matches"] == [{"rowIndex": 1, "title": "首页", "status": "error"}], inspection

        updated = run(
            "update",
            "--csv",
            str(csv_path),
            "--title",
            "首页",
            "--expect-status",
            "error",
            "--status",
            "doing",
        )
        assert updated.returncode == 0, updated.stderr
        result = json.loads(updated.stdout)
        assert result["previousStatus"] == "error" and result["status"] == "doing", result
        assert csv_path.read_bytes() == original.replace(b'"error"', b'"doing"', 1)
        assert not list(root.glob(".*.iff-tmp-*")), list(root.iterdir())

        metadata = root / "metadata.csv"
        metadata_original = (
            b"\xef\xbb\xbf" + "编号,标题,状态,error,spec_dir\r\n1,首页,error,旧错误,old/spec\r\n".encode()
        )
        metadata.write_bytes(metadata_original)
        metadata_update = run(
            "update",
            "--csv",
            str(metadata),
            "--title",
            "首页",
            "--expect-status",
            "error",
            "--status",
            "doing",
            "--set-column",
            "error=设计源缺少 paint source",
            "--set-column",
            "spec_dir=/tmp/spec",
        )
        assert metadata_update.returncode == 0, metadata_update.stderr
        metadata_result = json.loads(metadata_update.stdout)
        assert metadata_result["updatedColumns"] == {
            "error": "设计源缺少 paint source",
            "spec_dir": "/tmp/spec",
        }, metadata_result
        assert metadata.read_bytes() == (
            b"\xef\xbb\xbf"
            + "编号,标题,状态,error,spec_dir\r\n"
            "1,首页,doing,设计源缺少 paint source,/tmp/spec\r\n".encode()
        )
        metadata_refine = run(
            "update",
            "--csv",
            str(metadata),
            "--title",
            "首页",
            "--expect-status",
            "doing",
            "--status",
            "doing",
            "--set-column",
            "error=设计源缺少 4 个 paint source",
        )
        assert metadata_refine.returncode == 0, metadata_refine.stderr
        refined_result = json.loads(metadata_refine.stdout)
        assert refined_result["previousStatus"] == "doing"
        assert refined_result["status"] == "doing"
        assert refined_result["updatedColumns"] == {"error": "设计源缺少 4 个 paint source"}

        redundant_metadata = run(
            "update",
            "--csv",
            str(metadata),
            "--title",
            "首页",
            "--expect-status",
            "doing",
            "--status",
            "doing",
            "--set-column",
            "error=设计源缺少 4 个 paint source",
        )
        assert redundant_metadata.returncode == 2, redundant_metadata
        assert "metadata update does not change any value" in redundant_metadata.stderr

        no_op = run(
            "update",
            "--csv",
            str(metadata),
            "--title",
            "首页",
            "--expect-status",
            "doing",
            "--status",
            "doing",
        )
        assert no_op.returncode == 2, no_op
        assert "same-status update requires --set-column" in no_op.stderr, no_op.stderr

        duplicate = root / "duplicate.csv"
        duplicate.write_bytes(
            fixture(
                '1,首页,"A","error",'.encode(),
                '2,首页,"B","error",'.encode(),
            )
        )
        duplicate_before = duplicate.read_bytes()
        rejected = run(
            "update",
            "--csv",
            str(duplicate),
            "--title",
            "首页",
            "--expect-status",
            "error",
            "--status",
            "doing",
        )
        assert rejected.returncode == 2, rejected
        assert "expected exactly one active row" in rejected.stderr, rejected.stderr
        assert duplicate.read_bytes() == duplicate_before

        export_csv = root / "export.csv"
        export_out = root / "row.json"
        interaction_out = root / "interaction.txt"
        ui_notes_out = root / "ui_notes.txt"
        api_out = root / "api.txt"
        export_csv.write_text(
            "\ufeff编号,标题,设计稿地址,UI补充描述,交互描述,接口描述,状态,error,spec_dir\r\n"
            "2,首页,https://example.test/design,视觉补充,\"点击 Apply 后请求接口\n失败时展示错误\",/home/products,error,旧错误,old/spec\r\n",
            encoding="utf-8",
            newline="",
        )
        exported = run(
            "export",
            "--csv",
            str(export_csv),
            "--title",
            "首页",
            "--expect-status",
            "error",
            "--out",
            str(export_out),
            "--interaction-out",
            str(interaction_out),
            "--ui-notes-out",
            str(ui_notes_out),
            "--api-out",
            str(api_out),
        )
        assert exported.returncode == 0, exported.stderr
        assert interaction_out.read_text(encoding="utf-8") == "点击 Apply 后请求接口\n失败时展示错误"
        assert ui_notes_out.read_text(encoding="utf-8") == "视觉补充"
        assert api_out.read_text(encoding="utf-8") == "/home/products"
        exported_row = json.loads(export_out.read_text(encoding="utf-8"))
        assert exported_row == {
            "api": "/home/products",
            "design_url": "https://example.test/design",
            "error": "旧错误",
            "id": "2",
            "interaction": "点击 Apply 后请求接口\n失败时展示错误",
            "row_number": 1,
            "spec_dir": "old/spec",
            "status": "error",
            "title": "首页",
            "ui_notes": "视觉补充",
        }, exported_row

        english_csv = root / "english.csv"
        english_out = root / "english-row.json"
        english_csv.write_text(
            "id,title,design_url,ui_notes,interaction,api,status,error,spec_dir\n"
            "7,Home,https://example.test/home,notes,tap refresh,/home/products,doing,,spec/home\n",
            encoding="utf-8",
        )
        exported_english = run(
            "export",
            "--csv",
            str(english_csv),
            "--title",
            "Home",
            "--expect-status",
            "doing",
            "--out",
            str(english_out),
        )
        assert exported_english.returncode == 0, exported_english.stderr
        english_row = json.loads(english_out.read_text(encoding="utf-8"))
        assert english_row["interaction"] == "tap refresh"
        assert english_row["ui_notes"] == "notes"
        assert english_row["api"] == "/home/products"

    skill_text = SKILL.read_text(encoding="utf-8")
    assert "export --csv <sheet.csv>" in skill_text
    assert "printf '%s' \"$ROW_INTERACTION\"" not in skill_text
    print("PASS: CSV status update/export is semantic, atomic, unique-row guarded, and byte-format preserving")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
