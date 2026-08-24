"""Tests for validate.py — _extract_string_literals raw-string handling."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate import _extract_string_literals


class TestExtractStringLiterals(unittest.TestCase):

    def test_normal_strings_extracted(self):
        source = 'val a = "hello"\nval b = "world"'
        literals = _extract_string_literals(source)
        self.assertIn("hello", literals)
        self.assertIn("world", literals)

    def test_raw_string_does_not_poison_subsequent_literals(self):
        """Triple-quoted raw string with odd embedded quotes desyncs the regex."""
        source = 'val x = """hello "world"""\nval y = "target text"'
        literals = _extract_string_literals(source)
        self.assertIn("target text", literals)


if __name__ == "__main__":
    unittest.main()
