# Fixture source root classification self-check

Rules: `~/.agents/skills/iff/SKILL.md`

Reviewed artifacts:

- `~/.agents/skills/iff/scripts/check_fixture_source.py`
- `~/.agents/skills/iff/scripts/selftest_check_fixture_source_root_named_test.py`

| Criterion | Evidence | Result |
| --- | --- | --- |
| Classification is independent of ancestor/root basenames | `relative_path = path.relative_to(root)` precedes the `"test" in relative_path.parts` classification. | ✅ |
| A root named `test` keeps runtime code in the runtime set | The regression creates `<tmp>/test/lib/home_page.dart`; the public checker CLI passes instead of reporting `runtime_refs=[]`. | ✅ |
| A real root-relative `test/` directory remains test code | The same regression creates `<tmp>/test/test/home_page_test.dart`; the strict shared-symbol gate passes only with both test and runtime references present. | ✅ |
| Regression demonstrated the original failure | Before the implementation change, the new selftest exited 1 with `test_refs=['HomeVisualFixture'] runtime_refs=[]`. | ✅ |
| Focused fixture-gate tests pass | New root-name regression, assembly fixture gate order, assembly runtime target, and assembly completion evidence selftests all exit 0. | ✅ |
| Pipeline inventory remains valid | `verify_pipeline_scripts.py --skill-dir ~/.agents/skills/iff` reports `ok 71 scripts`. | ✅ |
| Syntax and whitespace checks pass | `py_compile` exits 0; scoped tracked diff check is clean; the new-file `--check` output has no whitespace errors. | ✅ |
| Scope remains inside generic iFF skill | Only the checker, its focused selftest, and this audit record were changed by this repair; no project business file was accessed or edited. | ✅ |

STATUS: PASS
