#!/usr/bin/env python3
"""Generate the XCTest source that emits a native ICP accessibility trace."""
from __future__ import annotations

import argparse
from pathlib import Path


SOURCE = '''import Foundation
import XCTest

final class ICPVisualTraceTests: XCTestCase {
    func testCaptureICPVisualTrace() throws {
        let app = XCUIApplication()
        app.launch()
        let elements = app.descendants(matching: .any).allElementsBoundByIndex
        let records: [[String: Any]] = elements.map { element in
            let frame = element.frame
            return [
                "identifier": element.identifier,
                "label": element.label,
                "frame": [
                    "x": Double(frame.origin.x),
                    "y": Double(frame.origin.y),
                    "width": Double(frame.size.width),
                    "height": Double(frame.size.height),
                ],
            ]
        }
        guard let output = ProcessInfo.processInfo.environment["ICP_TRACE_OUTPUT"],
              !output.isEmpty else {
            XCTFail("ICP_TRACE_OUTPUT is required")
            return
        }
        let payload: [String: Any] = [
            "kind": "icp.ios-native-view-trace.v1",
            "schema_version": 1,
            "elements": records,
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        try data.write(to: URL(fileURLWithPath: output), options: [.atomic])
    }
}
'''


def generate(path: Path) -> None:
    if path.suffix != ".swift":
        raise ValueError("XCTest harness output must be a .swift file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()
    output = Path(arguments.out)
    try:
        generate(output)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"ok iOS trace harness: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SOURCE", "generate"]
