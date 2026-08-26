import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lanhu_fetch.py"
SPEC = importlib.util.spec_from_file_location("lanhu_fetch", SCRIPT)
LANHU_FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LANHU_FETCH)


class ResolveCookieTest(unittest.TestCase):
    def test_reads_codex_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            dotenv = home / ".codex" / "mcp" / "lanhu-mcp" / ".env"
            dotenv.parent.mkdir(parents=True)
            dotenv.write_text('LANHU_COOKIE="codex-cookie"\n', encoding="utf-8")

            with patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                os.environ.pop("LANHU_COOKIE", None)
                self.assertEqual(LANHU_FETCH.resolve_cookie(None), "codex-cookie")

    def test_does_not_read_claude_dotenv(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            dotenv = home / ".claude" / "mcp" / "lanhu-mcp" / ".env"
            dotenv.parent.mkdir(parents=True)
            dotenv.write_text('LANHU_COOKIE="legacy-cookie"\n', encoding="utf-8")

            with patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                os.environ.pop("LANHU_COOKIE", None)
                self.assertIsNone(LANHU_FETCH.resolve_cookie(None))


if __name__ == "__main__":
    unittest.main()
