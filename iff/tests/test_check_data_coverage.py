from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_data_coverage.py"


def run_slot_coverage(root: Path, source: str) -> subprocess.CompletedProcess[str]:
    bindings = root / "data_slot_bindings.json"
    runtime = root / "data_runtime_manifest.json"
    tests = root / "test"
    tests.mkdir()
    bindings.write_text(
        json.dumps(
            {
                "bindings": [
                    {
                        "node": "amount-node",
                        "binding": {
                            "field": {
                                "endpoint": "/loan",
                                "method": "GET",
                                "status": "200",
                                "jsonPath": "$.amount",
                                "type": "number",
                            },
                            "transform": "formatNaira",
                        },
                        "confirmedByModel": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
    (tests / "data_test.dart").write_text(source, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--bindings",
            str(bindings),
            "--runtime-manifest",
            str(runtime),
            "--test-root",
            str(tests),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def run_repo_coverage(root: Path, source: str) -> subprocess.CompletedProcess[str]:
    bindings = root / "data_slot_bindings.json"
    runtime = root / "data_runtime_manifest.json"
    tests = root / "test"
    tests.mkdir()
    bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
    runtime.write_text(
        json.dumps(
            {
                "operations": [
                    {
                        "id": "fetchLoan",
                        "method": "GET",
                        "endpoint": "/loan/{id}",
                        "publicMethod": "fetchLoan",
                        "requiredStates": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tests / "data_test.dart").write_text(source, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--bindings",
            str(bindings),
            "--runtime-manifest",
            str(runtime),
            "--test-root",
            str(tests),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def run_state_coverage(root: Path, source: str, state_targets: dict | None = None) -> subprocess.CompletedProcess[str]:
    bindings = root / "data_slot_bindings.json"
    runtime = root / "data_runtime_manifest.json"
    tests = root / "test"
    tests.mkdir()
    bindings.write_text(json.dumps({"bindings": []}), encoding="utf-8")
    operation = {
        "id": "fetchLoan",
        "method": "GET",
        "endpoint": "/loan/{id}",
        "publicMethod": "fetchLoan",
        "requiredStates": ["loading"],
    }
    if state_targets is not None:
        operation["stateTargets"] = state_targets
    runtime.write_text(json.dumps({"operations": [operation]}), encoding="utf-8")
    repo_source = (
        "test('DATA-REPO:fetchLoan', () async {"
        " final server = await HttpServer.bind('127.0.0.1', 0);"
        " server.listen((request) {"
        "  expect(request.method, 'GET');"
        "  expect(request.uri.path, '/loan/42');"
        "  request.response.statusCode = 200;"
        "  expect(request.response.statusCode, 200);"
        "  request.response.write('{\"amount\":10}');"
        "  request.response.close();"
        " });"
        " final result = await repository.fetchLoan('42');"
        " expect(result.amount, 10);"
        " await server.close();"
        "});"
    )
    (tests / "data_test.dart").write_text(repo_source + source, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--bindings",
            str(bindings),
            "--runtime-manifest",
            str(runtime),
            "--test-root",
            str(tests),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class CheckDataCoverageTest(unittest.TestCase):
    def test_repository_case_requires_real_local_http_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_coverage(
                Path(tmp),
                "test('DATA-REPO:fetchLoan', () async { expect(true, true); });",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing local HTTP boundary", result.stdout + result.stderr)

    def test_repository_case_requires_declared_public_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_coverage(
                Path(tmp),
                "test('DATA-REPO:fetchLoan', () async {"
                " final server = await HttpServer.bind('127.0.0.1', 0);"
                " expect(true, true);"
                " await server.close();"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing public repository call fetchLoan", result.stdout + result.stderr)

    def test_repository_case_requires_exact_http_request_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_coverage(
                Path(tmp),
                "test('DATA-REPO:fetchLoan', () async {"
                " final server = await HttpServer.bind('127.0.0.1', 0);"
                " final result = await repository.fetchLoan('42');"
                " expect(result.amount, 10);"
                " await server.close();"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing HTTP request assertion GET /loan/{id}", result.stdout + result.stderr)

    def test_repository_case_requires_http_status_assertion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_coverage(
                Path(tmp),
                "test('DATA-REPO:fetchLoan', () async {"
                " final server = await HttpServer.bind('127.0.0.1', 0);"
                " final request = await server.first;"
                " expect(request.method, 'GET');"
                " expect(request.uri.path, '/loan/42');"
                " final result = await repository.fetchLoan('42');"
                " expect(result.amount, 10);"
                " await server.close();"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing HTTP status assertion", result.stdout + result.stderr)

    def test_repository_case_requires_mapped_result_assertion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_coverage(
                Path(tmp),
                "test('DATA-REPO:fetchLoan', () async {"
                " final server = await HttpServer.bind('127.0.0.1', 0);"
                " final request = await server.first;"
                " expect(request.method, 'GET');"
                " expect(request.uri.path, '/loan/42');"
                " expect(request.response.statusCode, 200);"
                " await repository.fetchLoan('42');"
                " expect(true, true);"
                " await server.close();"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing mapped result assertion", result.stdout + result.stderr)

    def test_repository_case_through_local_http_and_public_api_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_repo_coverage(
                Path(tmp),
                "test('DATA-REPO:fetchLoan', () async {"
                " final server = await HttpServer.bind('127.0.0.1', 0);"
                " server.listen((request) {"
                "  expect(request.method, 'GET');"
                "  expect(request.uri.path, '/loan/42');"
                "  request.response.statusCode = 200;"
                "  expect(request.response.statusCode, 200);"
                "  request.response.write('{\"amount\":10}');"
                "  request.response.close();"
                " });"
                " final result = await repository.fetchLoan('42');"
                " expect(result.amount, 10);"
                " await server.close();"
                "});",
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_state_case_must_be_a_widget_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_state_coverage(
                Path(tmp),
                "test('DATA-STATE:fetchLoan:loading', () { expect(true, true); });",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("not declared in testWidgets", result.stdout + result.stderr)

    def test_state_case_requires_structured_runtime_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_state_coverage(
                Path(tmp),
                "testWidgets('DATA-STATE:fetchLoan:loading', (tester) async {"
                " await tester.pumpWidget(const LoanApp());"
                " expect(true, true);"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing structured state target", result.stdout + result.stderr)

    def test_state_case_requires_public_runtime_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_state_coverage(
                Path(tmp),
                "testWidgets('DATA-STATE:fetchLoan:loading', (tester) async {"
                " expect(true, true);"
                "});",
                {"loading": {"key": "iff:loan-loading", "text": "Loading loan"}},
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing public runtime surface", result.stdout + result.stderr)

    def test_state_case_requires_exact_target_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_state_coverage(
                Path(tmp),
                "testWidgets('DATA-STATE:fetchLoan:loading', (tester) async {"
                " await tester.pumpWidget(const LoanApp());"
                " expect(find.text('Loading loan'), findsOneWidget);"
                "});",
                {"loading": {"key": "iff:loan-loading", "text": "Loading loan"}},
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing exact state target iff:loan-loading", result.stdout + result.stderr)

    def test_state_case_requires_exact_visible_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_state_coverage(
                Path(tmp),
                "testWidgets('DATA-STATE:fetchLoan:loading', (tester) async {"
                " await tester.pumpWidget(const LoanApp());"
                " expect(find.byKey(const ValueKey('iff:loan-loading')), findsOneWidget);"
                "});",
                {"loading": {"key": "iff:loan-loading", "text": "Loading loan"}},
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing visible state text Loading loan", result.stdout + result.stderr)

    def test_state_case_through_public_runtime_and_exact_observable_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_state_coverage(
                Path(tmp),
                "testWidgets('DATA-STATE:fetchLoan:loading', (tester) async {"
                " await tester.pumpWidget(const LoanApp());"
                " expect(find.byKey(const ValueKey('iff:loan-loading')), findsOneWidget);"
                " expect(find.text('Loading loan'), findsOneWidget);"
                "});",
                {"loading": {"key": "iff:loan-loading", "text": "Loading loan"}},
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_slot_case_requires_public_runtime_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_slot_coverage(
                Path(tmp),
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " expect(true, true);"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing public runtime surface", result.stdout + result.stderr)

    def test_slot_case_requires_exact_target_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_slot_coverage(
                Path(tmp),
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " await tester.pumpWidget(const LoanApp());"
                " expect(true, true);"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing exact slot target iff:amount-node", result.stdout + result.stderr)

    def test_slot_case_requires_bound_field_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_slot_coverage(
                Path(tmp),
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " await tester.pumpWidget(const LoanApp());"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("missing bound field $.amount", result.stdout + result.stderr)

    def test_slot_case_requires_two_distinct_visible_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_slot_coverage(
                Path(tmp),
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const LoanApp());"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                " expect(find.text('₦10'), findsOneWidget);"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("needs two distinct visible assertions", result.stdout + result.stderr)

    def test_slot_case_requires_two_distinct_bound_field_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_slot_coverage(
                Path(tmp),
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 10}));"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                " expect(find.text('₦10'), findsOneWidget);"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 10}));"
                " expect(find.text('₦20'), findsOneWidget);"
                "});",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("needs two distinct bound field inputs", result.stdout + result.stderr)

    def test_slot_case_with_bound_inputs_and_visible_outputs_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_slot_coverage(
                Path(tmp),
                "testWidgets('DATA-SLOT:amount-node', (tester) async {"
                " const fieldPath = '$.amount';"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 10}));"
                " expect(find.byKey(const ValueKey('iff:amount-node')), findsOneWidget);"
                " expect(find.text('₦10'), findsOneWidget);"
                " await tester.pumpWidget(const LoanApp(response: {'amount': 20}));"
                " expect(find.text('₦20'), findsOneWidget);"
                "});",
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_case_name_without_real_test_widget_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindings = root / "data_slot_bindings.json"
            runtime = root / "data_runtime_manifest.json"
            tests = root / "test"
            tests.mkdir()
            bindings.write_text(
                json.dumps(
                    {
                        "bindings": [
                            {
                                "node": "amount-node",
                                "binding": {
                                    "field": {
                                        "endpoint": "/loan",
                                        "method": "GET",
                                        "status": "200",
                                        "jsonPath": "$.amount",
                                        "type": "number",
                                    },
                                    "transform": "formatNaira",
                                },
                                "confirmedByModel": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            runtime.write_text(json.dumps({"operations": []}), encoding="utf-8")
            (tests / "data_test.dart").write_text(
                "// DATA-SLOT:amount-node\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--bindings",
                    str(bindings),
                    "--runtime-manifest",
                    str(runtime),
                    "--test-root",
                    str(tests),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("not declared in testWidgets", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
