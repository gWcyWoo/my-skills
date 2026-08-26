import importlib.util
from pathlib import Path
import ssl
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "icps_google_sheets_mcp.py"
SPEC = importlib.util.spec_from_file_location("icps_google_sheets_mcp", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeHttp:
    def __init__(self):
        self.close_count = 0

    def close(self):
        self.close_count += 1


class FakeRequest:
    def __init__(self):
        self.http = FakeHttp()


class GoogleSheetsMcpAdapterTest(unittest.TestCase):
    @patch.object(MODULE.time, "sleep")
    def test_rebuilds_transport_and_retries_broken_pipe(self, sleep):
        request = FakeRequest()
        results = iter([BrokenPipeError(32, "Broken pipe"), "ok"])

        def execute(_request, **_kwargs):
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return result

        actual = MODULE._execute_with_recovery(execute, request)

        self.assertEqual("ok", actual)
        self.assertEqual(1, request.http.close_count)
        sleep.assert_called_once_with(0.25)

    @patch.object(MODULE.time, "sleep")
    def test_retries_ssl_eof(self, sleep):
        request = FakeRequest()
        calls = 0

        def execute(_request, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ssl_error
            return "ok"

        ssl_error = ssl.SSLError("unexpected EOF")
        actual = MODULE._execute_with_recovery(execute, request)

        self.assertEqual("ok", actual)
        self.assertEqual(1, request.http.close_count)
        sleep.assert_called_once_with(0.25)

    @patch.object(MODULE.time, "sleep")
    def test_does_not_retry_non_transport_error(self, sleep):
        request = FakeRequest()

        def execute(_request, **_kwargs):
            raise ValueError("bad request")

        with self.assertRaisesRegex(ValueError, "bad request"):
            MODULE._execute_with_recovery(execute, request)

        self.assertEqual(0, request.http.close_count)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
