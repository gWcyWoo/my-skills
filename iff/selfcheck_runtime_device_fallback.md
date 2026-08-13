# Runtime Device Fallback Self-Check

- Rules path: `~/.agents/skills/iff/SKILL.md`
- Reviewed artifacts:
  - `SKILL.md`
  - `scripts/select_runtime_device.py`
  - `scripts/capture_runtime_screenshot.py`
  - `scripts/make_worker_prompt.py`
  - `scripts/verify_pipeline_scripts.py`
  - `scripts/selftest_runtime_device_fallback.py`
  - `scripts/selftest_assembly_runtime_device_contract.py`

## Contract audit

| Check | Evidence | Result |
|---|---|---|
| Generic scope only | Selector accepts platform/device/AVD inputs and sorted tool output; no business-project, feature, page, or named emulator is embedded. The prompt regression explicitly rejects `Pixel_9_Pro`. | ✅ |
| Deterministic Android selection and iOS fallback | `select_runtime_device.py` selects only ready `emulator-*` devices, sorts AVDs, then uses sorted available iOS Simulator data. `fallbackReason` is written at lines 285/304. | ✅ |
| Android launch errors are actionable | `select_runtime_device.py:157` includes the AVD name, exit code, and captured launch diagnostic when an emulator exits before readiness. | ✅ |
| No indefinite device wait | `run_bounded` is defined at `select_runtime_device.py:34`; timeout cleanup terminates the process group with SIGTERM/SIGKILL at lines 84/88. The assembly prompt at `make_worker_prompt.py:426` forbids `adb wait-for-device`. | ✅ |
| Real fallback screenshot evidence | `capture_runtime_screenshot.py:152` preserves `actual_source=simulator_screenshot`; the iOS fallback regression asserts the same provenance at `selftest_runtime_device_fallback.py:152`. | ✅ |
| Existing build/lock/repair guards preserved | The prompt keeps selected-platform build outside the lock, limits the lock to install/launch/capture, releases on every exit, and permits only one re-capture. `SKILL.md:374` keeps real `adb screencap`/`simctl screenshot` and reference-provenance prohibitions. | ✅ |
| Pipeline inventory and worker contract updated | `verify_pipeline_scripts.py:35` requires the selector and line 89 requires the runtime fallback regression; generated assembly prompt regression verifies selector-before-build-before-capture ordering. | ✅ |

## Regression and verification audit

| Command or suite | Evidence | Result |
|---|---|---|
| Focused runtime fallback | Broken generic Android AVD exits 1 with stderr; selector falls back to booted iOS, captures `actual.png`, writes simulator provenance, and kills a hanging adb child process before the 3-second test deadline. | ✅ |
| Focused assembly contract | `selftest_assembly_runtime_device_contract.py` proves automatic selector use, Android to iOS fallback, bounded timeouts, no `adb wait-for-device`, and no hardcoded Pixel profile. | ✅ |
| Assembly bounded context | Eight-board prompt is 17,998 bytes and grows 0 bytes for seven added boards; 18,000-byte hard gate remains intact. | ✅ |
| Full project-independent suite | 38/38 `selftest_*.py` tests passed with required skill-dir arguments. | ✅ |
| Canvas integration harness | Disposable `/private/tmp` Flutter project passed both regression corpus cases; generated canvas, Flutter analyze, trace tests, and render fidelity were green. | ✅ |
| Inventory and syntax | `verify_pipeline_scripts.py` reports 80 scripts; `python3 -m compileall -q scripts` passed. | ✅ |
| Patch hygiene | Scoped `git diff --check` and trailing-whitespace audit passed. | ✅ |

No issues remained after the process-group timeout correction.

STATUS: PASS
