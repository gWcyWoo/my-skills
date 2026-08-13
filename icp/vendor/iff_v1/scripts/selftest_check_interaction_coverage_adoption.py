#!/usr/bin/env python3
from __future__ import annotations

from check_interaction_coverage import evidence_ok


def main() -> int:
    strict = {
        "guard": {"mode": "strict_tdd", "runId": "strict-run"},
        "red": {"run_id": "strict-run", "exit_code": 1, "command": "flutter test test/home"},
        "green": {"run_id": "strict-run", "exit_code": 0, "command": "flutter test test/home"},
    }
    assert evidence_ok(strict) == []

    adopted = {
        "guard": {"mode": "preexisting_green_adoption", "runId": "adopt-run"},
        "adoption": {
            "authorization": "preexisting-green",
            "run_id": "adopt-run",
            "exit_code": 0,
            "command": "flutter test test/home",
        },
        "green": {"run_id": "adopt-run", "exit_code": 0, "command": "flutter test test/home"},
    }
    assert evidence_ok(adopted) == []

    invalid = {**adopted, "adoption": {**adopted["adoption"], "authorization": ""}}
    assert "adoption evidence authorization is invalid" in evidence_ok(invalid)
    print("PASS: interaction coverage accepts strict RED and authorized preexisting GREEN evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
