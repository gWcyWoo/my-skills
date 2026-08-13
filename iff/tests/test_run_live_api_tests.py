from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_live_api_tests.py"
CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_live_api_evidence.py"


class LoanHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str]] = []
    response: object = {"amount": 10}
    content_type = "application/json"

    def do_GET(self) -> None:
        self.__class__.requests.append((self.command, self.path))
        body = json.dumps(self.__class__.response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", self.__class__.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class RunLiveApiTestsTest(unittest.TestCase):
    def test_runner_and_checker_execute_current_operation_over_real_http(self) -> None:
        LoanHandler.requests = []
        LoanHandler.response = {"amount": 10}
        LoanHandler.content_type = "application/json"
        server = ThreadingHTTPServer(("127.0.0.1", 0), LoanHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                contract = root / "api_contract.json"
                runtime = root / "data_runtime_manifest.json"
                requests = root / "live_api_requests.json"
                report = root / "live_api_report.json"
                contract.write_text(
                    json.dumps(
                        {
                            "endpoints": {
                                "/loan/{id}": {
                                    "GET": {
                                        "responses": {
                                            "200": {
                                                "mediaType": "application/json",
                                                "fields": {
                                                    "$.amount": {
                                                        "type": "number",
                                                        "required": True,
                                                        "nullable": False,
                                                        "enum": None,
                                                    }
                                                },
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                runtime.write_text(
                    json.dumps(
                        {
                            "operations": [
                                {
                                    "id": "fetchLoan",
                                    "method": "GET",
                                    "endpoint": "/loan/{id}",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                requests.write_text(
                    json.dumps(
                        {
                            "operations": {
                                "fetchLoan": {
                                    "pathParameters": {"id": "42"},
                                    "expectedStatus": 200,
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                base_url = f"http://127.0.0.1:{server.server_port}"

                run = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--api-contract",
                        str(contract),
                        "--runtime-manifest",
                        str(runtime),
                        "--requests",
                        str(requests),
                        "--base-url",
                        base_url,
                        "--out",
                        str(report),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(0, run.returncode, run.stdout + run.stderr)
                self.assertIn(("GET", "/loan/42"), LoanHandler.requests)
                payload = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual("run_live_api_tests.py", payload["generator"])
                self.assertEqual(["fetchLoan"], payload["checkedOperations"])

                checked = subprocess.run(
                    [
                        sys.executable,
                        str(CHECKER),
                        "--api-contract",
                        str(contract),
                        "--runtime-manifest",
                        str(runtime),
                        "--report",
                        str(report),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
                self.assertGreaterEqual(LoanHandler.requests.count(("GET", "/loan/42")), 2)

                LoanHandler.response = {"amount": "ten"}
                bad_report = root / "bad_live_api_report.json"
                rejected = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--api-contract",
                        str(contract),
                        "--runtime-manifest",
                        str(runtime),
                        "--requests",
                        str(requests),
                        "--base-url",
                        base_url,
                        "--out",
                        str(bad_report),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(0, rejected.returncode)
                bad_payload = json.loads(bad_report.read_text(encoding="utf-8"))
                self.assertIn("response field type differs", bad_payload["results"][0]["schemaFailures"][0])

                LoanHandler.response = {"amount": 10}
                LoanHandler.content_type = "text/plain"
                media_report = root / "media_live_api_report.json"
                wrong_media = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--api-contract",
                        str(contract),
                        "--runtime-manifest",
                        str(runtime),
                        "--requests",
                        str(requests),
                        "--base-url",
                        base_url,
                        "--out",
                        str(media_report),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(0, wrong_media.returncode)
                media_payload = json.loads(media_report.read_text(encoding="utf-8"))
                self.assertIn(
                    "response media type differs",
                    media_payload["results"][0]["schemaFailures"][0],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
