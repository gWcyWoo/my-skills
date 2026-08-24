"""icps 写回:canonical 角色单元格 → Google Sheets batch_update_cells 载荷。

脚本只做确定性变换(列位解析 + A1 range 拼装),MCP 调用留给模型——与归一同一分工。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
WRITEBACK = SCRIPTS / "sheet_writeback.py"
NORMALIZE = SCRIPTS / "sheet_normalize.py"
LOCAL = SCRIPTS / "icps_local.py"

from icps.tests.test_sheet_normalize import HEADER, row  # noqa: E402

ROLE_FIELDS = ["status", "pr", "reviews", "last_error", "lease_token", "lease_until"]


def a1_parse(rng):
    """'Sheet1!K2' → (2, 10)  —— 逆着脚本推,不共用它的实现。"""
    cell = rng.split("!", 1)[1]
    letters = "".join(c for c in cell if c.isalpha())
    digits = "".join(c for c in cell if c.isdigit())
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return int(digits), col - 1


def sh(*argv, expect=0):
    p = subprocess.run([sys.executable, *[str(a) for a in argv]],
                       capture_output=True, text=True)
    assert p.returncode == expect, f"rc={p.returncode}\n{p.stdout}\n{p.stderr}"
    return json.loads(p.stdout.strip().splitlines()[-1])


class Fixture:
    def __init__(self, values):
        self.tmp = Path(tempfile.mkdtemp())
        self.raw = self.tmp / "raw.json"
        self.sheet = self.tmp / "sheet.json"
        self.raw.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        sh(NORMALIZE, "--values", self.raw, "--out", self.sheet)


class TestWriteback(unittest.TestCase):

    def test_ranges_follow_header_names_not_positions(self):
        """角色列在生产表里不连续,range 必须由表头名字推出。"""
        f = Fixture([HEADER, row(title="登录", fstatus="ready")])
        res = sh(WRITEBACK, "--values", f.raw, "--link", f.sheet, "--sheet", "Sheet1",
                 "--role", "frontend", "--row-ids", "r2")
        by_field = {u["field"]: u for u in res["updates"]}
        self.assertEqual(set(by_field), set(ROLE_FIELDS))
        # HEADER: frontend status=10(K), pr=11(L), reviews=12(M),
        #         last_error=16(Q), lease_token=17(R), lease_until=18(S)
        self.assertEqual(by_field["status"]["range"], "Sheet1!K2")
        self.assertEqual(by_field["pr"]["range"], "Sheet1!L2")
        self.assertEqual(by_field["reviews"]["range"], "Sheet1!M2")
        self.assertEqual(by_field["last_error"]["range"], "Sheet1!Q2")
        self.assertEqual(by_field["lease_token"]["range"], "Sheet1!R2")
        self.assertEqual(by_field["lease_until"]["range"], "Sheet1!S2")

    def test_only_the_requested_role_is_written(self):
        """写回 frontend 不得碰 backend 的格子。"""
        f = Fixture([HEADER, row(title="登录", fstatus="ready", bstatus="review")])
        res = sh(WRITEBACK, "--values", f.raw, "--link", f.sheet, "--sheet", "Sheet1",
                 "--role", "frontend", "--row-ids", "r2")
        cols = {u["range"] for u in res["updates"]}
        self.assertNotIn("Sheet1!N2", cols)  # backend status

    def test_null_canonical_value_becomes_empty_string(self):
        """canonical 的 null 表示该格应被清空,不能写成字面 'None'。"""
        f = Fixture([HEADER, row(title="登录", fstatus="ready")])
        res = sh(WRITEBACK, "--values", f.raw, "--link", f.sheet, "--sheet", "Sheet1",
                 "--role", "frontend", "--row-ids", "r2")
        by_field = {u["field"]: u["value"] for u in res["updates"]}
        self.assertEqual(by_field["status"], "ready")
        self.assertEqual(by_field["pr"], "")

    def test_unknown_row_halts(self):
        f = Fixture([HEADER, row(title="登录", fstatus="ready")])
        res = sh(WRITEBACK, "--values", f.raw, "--link", f.sheet, "--sheet", "Sheet1",
                 "--role", "frontend", "--row-ids", "r99", expect=1)
        self.assertEqual(res["errors"][0]["code"], "unknown_row")

    def test_missing_role_column_halts(self):
        """表头缺角色列 → 无处可写,零输出停机,不能猜位置。"""
        f = Fixture([HEADER, row(title="登录", fstatus="ready")])
        header = [h for h in HEADER if h != "frontend lease_until"]
        f.raw.write_text(json.dumps([header, [""] * len(header)], ensure_ascii=False),
                         encoding="utf-8")
        res = sh(WRITEBACK, "--values", f.raw, "--link", f.sheet, "--sheet", "Sheet1",
                 "--role", "frontend", "--row-ids", "r2", expect=1)
        self.assertEqual(res["errors"][0]["code"], "missing_column")


class TestWritebackRoundTrip(unittest.TestCase):
    """集成:claim 改 canonical → writeback 出载荷 → 回贴原表 → 重新归一必须一致。"""

    def test_claim_then_writeback_reproduces_canonical(self):
        values = [HEADER,
                  row(title="登录", route="signin", fstatus="doing",
                      ftoken="tok-f", funtil="2026-01-01T00:00:00+00:00"),
                  row(title="首页", route="home", fstatus="ready")]
        f = Fixture(values)

        sh(LOCAL, "claim", "--link", f.sheet, "--role", "frontend",
           "--row-ids", "r2", "--status", "review", "--lease-token", "tok-f",
           "--pr", "MR-42")

        res = sh(WRITEBACK, "--values", f.raw, "--link", f.sheet, "--sheet", "Sheet1",
                 "--role", "frontend", "--row-ids", "r2")

        # 把 updates 回贴到原始 values 上,模拟 batch_update_cells 的效果
        patched = [list(r) for r in values]
        for u in res["updates"]:
            row_index, col_index = a1_parse(u["range"])
            patched[row_index - 1][col_index] = u["value"]

        tmp = Path(tempfile.mkdtemp())
        raw2, sheet2 = tmp / "raw.json", tmp / "sheet.json"
        raw2.write_text(json.dumps(patched, ensure_ascii=False), encoding="utf-8")
        sh(NORMALIZE, "--values", raw2, "--out", sheet2)

        after = json.loads(f.sheet.read_text(encoding="utf-8"))
        reread = json.loads(sheet2.read_text(encoding="utf-8"))
        self.assertEqual(after["rows"], reread["rows"])
        self.assertEqual(reread["rows"][0]["roles"]["frontend"]["status"], "review")
        self.assertEqual(reread["rows"][0]["roles"]["frontend"]["pr"], "MR-42")
        self.assertIsNone(reread["rows"][0]["roles"]["frontend"]["lease_token"])


if __name__ == "__main__":
    unittest.main()
