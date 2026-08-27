#!/usr/bin/env python3
"""ICP Stage 3 — test_lint: 测试代码质量静态检查 (多语言)。

合约驱动: 每个交互绑定测试模式,模型按模式写测试,脚本按模式验证结构。

有效模式 (交互→模式绑定):
  P1 ui-interaction    — UI 渲染 + 设备操作 + UI 状态断言
  P2 value-assertion   — assertEquals/expect 用非 SUT 调用的 expected
  P3 error-handling    — assertThrows/assertFailsWith 验证异常
  P4 snapshot          — 快照比对测试

反模式检测 (A-E, 二次防线):

A 回调绑定 (Callback Binding) — 断言回调副作用而非可观测状态:
  A1 callback-counter   — var n=0; onClick={n++}; assertEquals(1,n)
  A2 callback-flag      — var ok=false; onDone={ok=true}; assertTrue(ok)
  A3 callback-capture   — var s=""; onSelect={s=it}; assertEquals("a",s)
  A4 callback-collect   — val l=mutableListOf(); on={l.add(it)}; assertEquals(...)

B Mock 回声 (Mock Echo) — 断言 mock 设定值:
  B1 mock-assert        — val s=mockk<S>(); assertEquals(1,s.c)
  B2 verify-only        — verify(repo).save(any()) 只验证调用不验证结果

D 烟雾断言 (Smoke-Only) — 只检查存在/不崩溃:
  D1 no-assertion        — 测试无断言
  D2 weak-assertion      — 仅 assertNotNull/isNotEmpty/assertIs 无值断言

E 实现耦合 (Implementation Coupling) — 断言内部实现细节:
  E1 verify-order        — verifyOrder { a(); b() }
  E2 verify-count        — verify(exactly=1) { ... }

F 白名单 (UI 测试必须存在):
  F1 no-device-action    — UI 测试无设备操作
  F2 no-ui-query         — UI 测试无 UI 状态断言

G 正面分类 (每个测试必须命中一个有效模式):
  unclassified — 无 @test-pattern 注解

支持: Kotlin, Java, Dart, Swift, ObjC, JS/TS, Python

用法:
  python3 test_lint.py <test_file_or_dir> [--json]
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Language configs
# ---------------------------------------------------------------------------

def _lang_config(lang):
    """Return regex patterns specific to *lang*."""

    if lang == "kotlin":
        return dict(
            test_func=re.compile(r"(?:@Test\b|fun test\w*\()"),
            assert_any=[
                re.compile(r"\bassert\w*\s*(?:<(?:[^<>]|<[^<>]*>)*>\s*)?[({]", re.I),
                re.compile(r"\bverify(?:Order)?\s*[\({]", re.I),
                re.compile(r"\bexpect\s*\(", re.I),
                re.compile(r"\.should\w*\(", re.I),
                re.compile(r"@Test\s*\(\s*expected\b", re.I),
            ],
            device_action=re.compile(
                r"\.perform(?:Click|TextInput|TouchInput|ScrollTo"
                r"|ScrollToIndex|ScrollToKey|ScrollToNode"
                r"|KeyInput|ImeAction)\s*[({]", re.I,
            ),
            ui_state_query=re.compile(
                r"\.assert(?:IsDisplayed|Exists|DoesNotExist|IsSelected"
                r"|IsNotSelected|TextEquals|TextContains|CountEquals"
                r"|ContentDescriptionEquals|IsEnabled|IsNotEnabled"
                r"|IsFocused|IsOn|IsOff|IsToggleable)\s*\("
                r"|\.fetchSemanticsNode\s*\("
                r"|\.captureToImage\s*\(", re.I,
            ),
            assert_eq_open=re.compile(
                r"\bassertEquals\s*\(", re.I,
            ),
            expected_pos="first",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:mockk|mock|spy|every|coEvery)\s*[<({]", re.I,
            ),
            counter_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*0\b"),
            counter_inc=re.compile(r"\b(\w+)\s*\+\+"),
            counter_assert=r"\b(?:assertEquals|assertThat)\s*\(\s*\d+\s*,\s*{var}\b",
            var_decl=re.compile(
                r'\bvar\s+(\w+)\s*(?::\s*\w[^=]*)?\s*=\s*(?:""'
                r"|''|0|false|null|emptyList\(\)|mutableListOf\(\))",
            ),
            callback_assign=re.compile(
                r"\bon\w+\s*=\s*\{[^}]*\b(\w+)\s*=(?!=)",
            ),
            actual_in_eq=re.compile(
                r"\b(?:assertEquals|assertThat)\s*\([^,]+,\s*(\w+)\b", re.I,
            ),
            ui_assert=re.compile(
                r"\.assert(?:IsDisplayed|Exists|DoesNotExist|IsSelected"
                r"|IsNotSelected|TextEquals|TextContains|CountEquals"
                r"|ContentDescriptionEquals|IsEnabled|IsNotEnabled"
                r"|IsFocused|IsOn|IsOff|IsToggleable)\s*\(", re.I,
            ),
            value_assert=re.compile(
                r"\b(?:assertEquals|assertThat)\s*\(", re.I,
            ),
            flag_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*false\b"),
            flag_assert=re.compile(r"\b(?:assertTrue|assertThat)\s*\(\s*(\w+)\s*\)"),
            collect_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*mutableListOf\s*\("),
            collect_mutate=re.compile(r"\b(\w+)\.add\s*\("),
            verify_only=re.compile(r"\bverify\s*[\({]"),
            weak_assert=re.compile(
                r"\bassertNotNull\s*\("
                r"|\bassertTrue\s*\(\s*\w+\.isNotEmpty\s*\(\s*\)\s*\)"
                r"|\bassertIs\s*<\w+>\s*\(",
            ),
            verify_order=re.compile(r"\bverifyOrder\s*\{"),
            verify_count=re.compile(r"\bverify\s*\(\s*(?:exactly|atLeast|atMost)\s*=\s*\d+"),
            error_assert=re.compile(
                r"\bassertThrows\s*[<(]"
                r"|\bassertFailsWith\s*[<(]"
                r"|\bshouldThrow\s*[<(]"
                r"|@Test\s*\(\s*expected\s*=",
            ),
            snapshot_assert=re.compile(
                r"\.captureToImage\s*\("
                r"|\.assertAgainstGolden\s*\("
                r"|\.compareAgainstBaseline\s*\(",
            ),
            block_delim="brace",
        )

    if lang == "java":
        return dict(
            test_func=re.compile(r"@Test\b"),
            assert_any=[
                re.compile(r"\bassert\w*\s*\(", re.I),
                re.compile(r"\bverify\s*\(", re.I),
                re.compile(r"@Test\s*\(\s*expected\b", re.I),
            ],
            device_action=re.compile(
                r"\.perform\s*\("
                r"|Espresso\.onView\s*\("
                r"|\.perform(?:Click|ScrollTo)\s*\("
                r"|ViewActions\.(?:click|typeText|swipe|scroll)\s*\(", re.I,
            ),
            ui_state_query=re.compile(
                r"\.check\s*\(\s*matches\s*\("
                r"|ViewMatchers\.(?:isDisplayed|isEnabled|withText)\s*\(", re.I,
            ),
            assert_eq_open=re.compile(
                r"\bassertEquals\s*\(", re.I,
            ),
            expected_pos="first",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:mock|spy|Mockito\.mock|Mockito\.spy)\s*\(", re.I,
            ),
            counter_decl=re.compile(r"\b(?:int|var)\s+(\w+)\s*=\s*0\s*;"),
            counter_inc=re.compile(r"\b(\w+)\s*\+\+"),
            counter_assert=r"\b(?:assertEquals|assertThat)\s*\(\s*\d+\s*,\s*{var}\b",
            var_decl=re.compile(
                r'\b(?:int|long|boolean|String|var)\s+(\w+)\s*=\s*(?:""'
                r"|0|false|null)\s*;",
            ),
            callback_assign=re.compile(
                r"\.(?:set)?[Oo]n\w+\s*\([^)]*->\s*[^)]*\b(\w+)\s*=(?!=)",
            ),
            actual_in_eq=re.compile(
                r"\b(?:assertEquals|assertThat)\s*\([^,]+,\s*(\w+)\b", re.I,
            ),
            ui_assert=re.compile(
                r"\.(?:check|assert)\s*\(\s*(?:matches|isDisplayed|isEnabled)", re.I,
            ),
            value_assert=re.compile(
                r"\b(?:assertEquals|assertThat)\s*\(", re.I,
            ),
            flag_decl=re.compile(r"\b(?:boolean|var)\s+(\w+)\s*=\s*false\s*;"),
            flag_assert=re.compile(r"\b(?:assertTrue|assertThat)\s*\(\s*(\w+)\s*\)"),
            collect_decl=re.compile(r"\b(?:var|List\s*<[^>]*>)\s+(\w+)\s*=\s*(?:new\s+ArrayList|List\.of\s*\(\s*\))"),
            collect_mutate=re.compile(r"\b(\w+)\.add\s*\("),
            verify_only=re.compile(r"\bverify\s*\("),
            weak_assert=re.compile(
                r"\bassertNotNull\s*\("
                r"|\bassertTrue\s*\(\s*\w+\.isEmpty\s*\(\s*\)\s*==\s*false"
                r"|\bassertFalse\s*\(\s*\w+\.isEmpty\s*\(\s*\)\s*\)"
                r"|\bassertInstanceOf\s*\(",
            ),
            verify_order=re.compile(r"\bInOrder\b.*\.verify\s*\("),
            verify_count=re.compile(r"\bverify\s*\(\s*\w+\s*,\s*(?:times|atLeast|atMost|never)\s*\("),
            error_assert=re.compile(
                r"\bassertThrows\s*\("
                r"|@Test\s*\(\s*expected\s*=",
            ),
            snapshot_assert=None,
            block_delim="brace",
        )

    if lang == "dart":
        return dict(
            test_func=re.compile(r"\b(?:test|testWidgets)\s*\("),
            assert_any=[
                re.compile(r"\bexpect\s*\("),
            ],
            device_action=re.compile(
                r"\btester\.(?:tap|enterText|drag|fling|longPress"
                r"|pumpAndSettle|ensureVisible|scrollUntilVisible)\s*\(", re.I,
            ),
            ui_state_query=re.compile(
                r"\bfind\.(?:text|byKey|byType|byIcon|byWidget"
                r"|byTooltip|widgetWithText|descendant)\s*\("
                r"|findsOneWidget|findsNothing|findsNWidgets|findsWidgets", re.I,
            ),
            assert_eq_open=re.compile(r"\bexpect\s*\("),
            expected_pos="second",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:Mock\w+|MockSpec)\s*\(", re.I,
            ),
            counter_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*0\s*;"),
            counter_inc=re.compile(r"\b(\w+)\s*\+\+"),
            counter_assert=r"\bexpect\s*\(\s*{var}\s*,\s*\d+",
            var_decl=re.compile(
                r"\bvar\s+(\w+)\s*=\s*(?:''|"
                r'""'
                r"|0|false|null)\s*;",
            ),
            callback_assign=re.compile(
                r"\bon\w+\s*:\s*\([^)]*\)\s*(?:=>|\{)[^}]*\b(\w+)\s*=(?!=)",
            ),
            actual_in_eq=re.compile(
                r"\bexpect\s*\(\s*(\w+)\b",
            ),
            ui_assert=re.compile(
                r"\bexpect\s*\(\s*find\.\w+|findsOneWidget|findsNothing"
                r"|findsNWidgets|findsWidgets", re.I,
            ),
            value_assert=re.compile(
                r"\bexpect\s*\((?:[^,()]|\([^()]*\))*,\s*(?:\d|\"[^\"]*\"|'[^']*'|true|false|null"
                r"|equals\s*\(|contains\s*\(|findsOneWidget|findsNothing"
                r"|findsNWidgets|findsWidgets)",
            ),
            flag_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*false\s*;"),
            flag_assert=re.compile(r"\bexpect\s*\(\s*(\w+)\s*,\s*(?:isTrue|true)\s*\)"),
            collect_decl=re.compile(r"\b(?:var|final)\s+(\w+)\s*=\s*(?:<[^>]*>)?\s*\[\s*\]\s*;"),
            collect_mutate=re.compile(r"\b(\w+)\.add\s*\("),
            verify_only=re.compile(r"\bverify\s*\("),
            weak_assert=re.compile(
                r"\bexpect\s*\(\s*\w+\s*,\s*isNotNull\s*\)"
                r"|\bexpect\s*\(\s*\w+\s*,\s*isNotEmpty\s*\)"
                r"|\bexpect\s*\(\s*\w+\s*,\s*isA\s*<",
            ),
            verify_order=None,
            verify_count=re.compile(r"\bverify\s*\(\s*\(\)\s*=>\s*\w+.*\)\.called\s*\(\s*\d+"),
            error_assert=re.compile(
                r"\bexpect\s*\([^)]+,\s*throwsA\s*\("
                r"|\bexpect\s*\([^)]+,\s*throws(?:Exception|ArgumentError|StateError|FormatException)",
            ),
            snapshot_assert=re.compile(
                r"\bmatchesGoldenFile\s*\("
                r"|\bexpectLater\s*\([^)]+,\s*matchesGoldenFile",
            ),
            block_delim="brace",
        )

    if lang == "swift":
        return dict(
            test_func=re.compile(r"\bfunc\s+test\w*\s*\("),
            assert_any=[
                re.compile(r"\bXCTAssert\w*\s*\("),
                re.compile(r"\bexpect\s*\("),
            ],
            device_action=re.compile(
                r"\.tap\s*\("
                r"|\.typeText\s*\("
                r"|\.swipe(?:Up|Down|Left|Right)\s*\("
                r"|\.press\s*\("
                r"|\.doubleTap\s*\(", re.I,
            ),
            ui_state_query=re.compile(
                r"\.exists\b"
                r"|\.isHittable\b"
                r"|\.isEnabled\b"
                r"|\.isSelected\b"
                r"|\.value\b"
                r"|\.label\b"
                r"|\.staticTexts\[", re.I,
            ),
            assert_eq_open=re.compile(r"\bXCTAssertEqual\s*\("),
            expected_pos="second",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:Mock\w+)\s*\(", re.I,
            ),
            counter_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*0\b"),
            counter_inc=re.compile(r"\b(\w+)\s*\+=\s*1"),
            counter_assert=r"\bXCTAssertEqual\s*\(\s*{var}\s*,\s*\d+",
            var_decl=re.compile(
                r'\bvar\s+(\w+)\s*(?::\s*\w+\??)?\s*=\s*(?:""'
                r"|0|false|nil)\b",
            ),
            callback_assign=re.compile(
                r"\bon\w+\s*=\s*\{[^}]*\b(\w+)\s*=(?!=)",
            ),
            actual_in_eq=re.compile(
                r"\bXCTAssertEqual\s*\(\s*(\w+)\b",
            ),
            ui_assert=re.compile(
                r"\.(?:exists|isHittable|isEnabled|isSelected)\b"
                r"|XCTAssert(?:True|False)\s*\(\s*app\.", re.I,
            ),
            value_assert=re.compile(
                r"\b(?:XCTAssertEqual)\s*\(", re.I,
            ),
            flag_decl=re.compile(r"\bvar\s+(\w+)\s*=\s*false\b"),
            flag_assert=re.compile(r"\bXCTAssertTrue\s*\(\s*(\w+)\s*\)"),
            collect_decl=re.compile(r"\bvar\s+(\w+)\s*(?::\s*\[[^\]]*\])?\s*=\s*\[\s*\]"),
            collect_mutate=re.compile(r"\b(\w+)\.append\s*\("),
            verify_only=None,
            weak_assert=re.compile(
                r"\bXCTAssertNotNil\s*\("
                r"|\bXCTAssertFalse\s*\(\s*\w+\.isEmpty\s*\)"
                r"|\bXCTAssert(?:True|False)\s*\(\s*\w+\s+is\s+\w+",
            ),
            verify_order=None,
            verify_count=None,
            error_assert=re.compile(
                r"\bXCTAssertThrowsError\s*\("
                r"|\bXCTAssertNoThrow\s*\(",
            ),
            snapshot_assert=re.compile(
                r"\bassertSnapshot\s*\("
                r"|\bverifySnapshot\s*\(",
            ),
            block_delim="brace",
        )

    if lang == "objc":
        return dict(
            test_func=re.compile(r"-\s*\(void\)\s*test\w*\b"),
            assert_any=[
                re.compile(r"\bXCTAssert\w*\s*\("),
                re.compile(r"\bOCMVerify\s*\(", re.I),
            ],
            device_action=re.compile(
                r"\[.*\btap\]"
                r"|\[.*\btypeText:.*\]"
                r"|\[.*\bswipe(?:Up|Down|Left|Right)\]", re.I,
            ),
            ui_state_query=re.compile(
                r"\.exists\b"
                r"|\.isHittable\b"
                r"|\.isEnabled\b"
                r"|\.staticTexts\[", re.I,
            ),
            assert_eq_open=re.compile(r"\b(?:XCTAssertEqual|XCTAssertEqualObjects)\s*\("),
            expected_pos="second",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:OCMClassMock|OCMProtocolMock|OCMStrictClassMock)\s*\(",
                re.I,
            ),
            counter_decl=re.compile(r"\b(?:__block\s+)?(?:NSInteger|NSUInteger|int)\s+(\w+)\s*=\s*0\s*;"),
            counter_inc=re.compile(r"\b(\w+)\s*\+\+"),
            counter_assert=r"\bXCTAssertEqual(?:Objects)?\s*\(\s*{var}\s*,\s*\d+",
            var_decl=re.compile(
                r"\b__block\s+\w+\s+(\w+)\s*=\s*(?:nil|0|NO)\s*;",
            ),
            callback_assign=re.compile(
                r"\^\s*(?:\([^)]*\))?\s*\{[^}]*\b(\w+)\s*=(?!=)",
            ),
            actual_in_eq=re.compile(
                r"\bXCTAssertEqual(?:Objects)?\s*\(\s*(\w+)\b",
            ),
            ui_assert=re.compile(
                r"\.(?:exists|isHittable|isEnabled|isSelected)\b",
            ),
            value_assert=re.compile(
                r"\b(?:XCTAssertEqual|XCTAssertEqualObjects)\s*\(", re.I,
            ),
            flag_decl=re.compile(r"\b__block\s+BOOL\s+(\w+)\s*=\s*NO\s*;"),
            flag_assert=re.compile(r"\bXCTAssertTrue\s*\(\s*(\w+)\s*\)"),
            collect_decl=re.compile(r"\b(\w+)\s*=\s*\[\s*NSMutableArray\s+new\s*\]"),
            collect_mutate=re.compile(r"\[(\w+)\s+addObject:"),
            verify_only=re.compile(r"\bOCMVerify\s*\("),
            weak_assert=re.compile(
                r"\bXCTAssertNotNil\s*\(",
            ),
            verify_order=None,
            verify_count=None,
            error_assert=re.compile(
                r"\bXCTAssertThrowsError\s*\("
                r"|\bXCTAssertNoThrow\s*\(",
            ),
            snapshot_assert=None,
            block_delim="brace",
        )

    if lang in ("js", "ts"):
        return dict(
            test_func=re.compile(r"\b(?:test|it|describe)\s*\("),
            assert_any=[
                re.compile(r"\bexpect\s*\("),
                re.compile(r"\bassert\s*[\.(]"),
            ],
            device_action=re.compile(
                r"\.click\s*\("
                r"|\.type\s*\("
                r"|userEvent\.(?:click|type|clear|selectOptions|upload)\s*\("
                r"|fireEvent\.(?:click|change|submit|input)\s*\(", re.I,
            ),
            ui_state_query=re.compile(
                r"screen\.(?:getBy|queryBy|findBy)\w+\s*\("
                r"|\.toBeInTheDocument\s*\("
                r"|\.toBeVisible\s*\("
                r"|\.toHaveTextContent\s*\("
                r"|\.toBeDisabled\s*\("
                r"|\.toBeEnabled\s*\(", re.I,
            ),
            assert_eq_open=re.compile(
                r"\bassert\.(?:strictEqual|deepStrictEqual|equal|deepEqual)\s*\(",
            ),
            expected_pos="second",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:jest\.fn|vi\.fn|sinon\.stub|sinon\.spy|jest\.spyOn)\s*\(",
                re.I,
            ),
            counter_decl=re.compile(r"\blet\s+(\w+)\s*=\s*0\s*;?"),
            counter_inc=re.compile(r"\b(\w+)\s*\+\+"),
            counter_assert=r"\bexpect\s*\(\s*{var}\s*\)",
            var_decl=re.compile(
                r"\blet\s+(\w+)\s*=\s*(?:''|"
                r'""'
                r"|0|false|null|undefined)\s*;?",
            ),
            callback_assign=re.compile(
                r"\bon\w+\s*=\s*(?:\([^)]*\)|(?:\w+))\s*=>\s*(?:\{[^}]*)?\b(\w+)\s*=(?!=)"
                r"|\bon\w+\s*=\s*\{[^}]*\b(\w+)\s*=(?!=)",
            ),
            actual_in_eq=re.compile(
                r"\bexpect\s*\(\s*(\w+)\b",
            ),
            ui_assert=re.compile(
                r"\.toBeInTheDocument\s*\("
                r"|\.toBeVisible\s*\("
                r"|\.toHaveTextContent\s*\("
                r"|\.toBeDisabled\s*\("
                r"|\.toBeEnabled\s*\("
                r"|screen\.getBy|screen\.queryBy|screen\.findBy", re.I,
            ),
            value_assert=re.compile(
                r"\bexpect\s*\((?:[^()]|\([^()]*\))*\)\s*\.to(?:Be|Equal|StrictEqual|Contain|Match"
                r"|Have(?:Length|TextContent|Attribute|Class|Style|Value))\s*\(",
                re.I,
            ),
            flag_decl=re.compile(r"\blet\s+(\w+)\s*=\s*false\s*;?"),
            flag_assert=re.compile(r"\bexpect\s*\(\s*(\w+)\s*\)\s*\.toBe(?:Truthy)?\s*\("),
            collect_decl=re.compile(r"\b(?:let|const)\s+(\w+)\s*=\s*\[\s*\]\s*;?"),
            collect_mutate=re.compile(r"\b(\w+)\.push\s*\("),
            verify_only=re.compile(r"\bexpect\s*\(\s*\w+\s*\)\s*\.toHaveBeenCalled"),
            weak_assert=re.compile(
                r"\.toBeDefined\s*\("
                r"|\.toBeTruthy\s*\("
                r"|\.not\.toBeNull\s*\("
                r"|\.toBeInstanceOf\s*\(",
            ),
            verify_order=None,
            verify_count=re.compile(r"\.toHaveBeenCalledTimes\s*\("),
            error_assert=re.compile(
                r"\.toThrow\s*\("
                r"|\.rejects\.toThrow\s*\("
                r"|expect\s*\(\s*\(\)\s*=>\s*.*\)\.toThrow",
            ),
            snapshot_assert=re.compile(
                r"\.toMatchSnapshot\s*\("
                r"|\.toMatchInlineSnapshot\s*\(",
            ),
            block_delim="brace",
        )

    if lang == "python":
        return dict(
            test_func=re.compile(r"\bdef\s+test_"),
            assert_any=[
                re.compile(r"\bassert\b"),
                re.compile(r"\bself\.assert\w+\s*\("),
            ],
            device_action=None,
            ui_state_query=None,
            assert_eq_open=re.compile(r"\bself\.(?:assertEqual|assertEquals)\s*\("),
            expected_pos="first",
            mock_decl=re.compile(
                r"\b(\w+)\s*=\s*(?:Mock|MagicMock|patch|create_autospec)\s*\(",
                re.I,
            ),
            counter_decl=re.compile(r"\b(\w+)\s*=\s*0\b"),
            counter_inc=re.compile(r"\b(\w+)\s*\+=\s*1"),
            counter_assert=r"\bself\.assert\w+\s*\(\s*\d+\s*,\s*{var}\b",
            var_decl=re.compile(
                r'\b(\w+)\s*=\s*(?:""'
                r"|''|0|False|None)\b",
            ),
            callback_assign=re.compile(
                r"\bon\w+\s*=\s*lambda[^:]*:\s*[^,]*\b(\w+)\b",
            ),
            actual_in_eq=re.compile(
                r"\bself\.assert\w+\s*\([^,]+,\s*(\w+)\b",
            ),
            ui_assert=None,
            value_assert=re.compile(
                r"\bself\.(?:assertEqual|assertEquals)\s*\(", re.I,
            ),
            flag_decl=re.compile(r"\b(\w+)\s*=\s*False\b"),
            flag_assert=re.compile(r"\bself\.assertTrue\s*\(\s*(\w+)\s*\)|\bassert\s+(\w+)\b"),
            collect_decl=re.compile(r"\b(\w+)\s*=\s*\[\s*\]"),
            collect_mutate=re.compile(r"\b(\w+)\.append\s*\("),
            verify_only=re.compile(r"\b\w+\.assert_called"),
            weak_assert=re.compile(
                r"\bself\.assertIsNotNone\s*\("
                r"|\bself\.assertIsInstance\s*\(",
            ),
            verify_order=re.compile(r"\b\w+\.assert_has_calls\s*\("),
            verify_count=re.compile(r"\b\w+\.assert_called_(?:once|with)\s*\("),
            error_assert=re.compile(
                r"\bself\.assertRaises\s*\("
                r"|\bpytest\.raises\s*\("
                r"|\bwith\s+self\.assertRaises\s*\(",
            ),
            snapshot_assert=None,
            block_delim="indent",
        )

    raise ValueError(f"unsupported lang: {lang}")


_EXT_TO_LANG = {
    ".kt": "kotlin", ".java": "java", ".dart": "dart",
    ".swift": "swift", ".m": "objc", ".h": "objc",
    ".ts": "ts", ".tsx": "ts", ".js": "js", ".jsx": "js",
    ".py": "python",
}


# ---------------------------------------------------------------------------
# JS chained assertions: expect(actual).toBe(expected)
# ---------------------------------------------------------------------------

_JS_CHAINED = re.compile(
    r"\bexpect\s*\(\s*(.+?)\s*\)\s*\.to(?:Be|Equal|StrictEqual|Have\w+)\s*\(\s*(.+?)\s*\)",
    re.I,
)

# SUT call: lowercaseVar.method/property.  Language-agnostic — the same shape
# in every supported language.  Everything else (constructors, literals, enum
# refs, collection builders) is treated as test-authored data.
_SUT_CALL = re.compile(r'^[a-z_]\w*\.')

# assertThat(actual).isEqualTo(expected) — AssertJ / Truth / Kotest
_ASSERTTHAT_CHAINED = re.compile(
    r"\bassertThat\s*\(\s*(.+?)\s*\)\s*\."
    r"(?:isEqualTo|isSameAs|containsExactly|contains|hasSize)"
    r"\s*\(\s*(.+?)\s*\)",
    re.I,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Violation:
    __slots__ = ("file", "line", "rule", "message")

    def __init__(self, file, line, rule, message):
        self.file = str(file)
        self.line = line
        self.rule = rule
        self.message = message

    def to_dict(self):
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
        }


def _extract_arg(text, start):
    """Extract balanced-paren argument from *start* (just after the open paren)."""
    depth = 1
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i].strip()
        elif ch == "," and depth == 1:
            return text[start:i].strip()
        i += 1
    return text[start:i].strip()


_ANNOTATION_LINE = re.compile(r'^\s*(?:@\w+(?:\s*\([^)]*\))?\s*)*(?://.*)?$')


def _is_annotation_block(lines_slice):
    """True when every line is blank, a comment, or pure annotations."""
    return all(l.lstrip().startswith('//') or _ANNOTATION_LINE.match(l) for l in lines_slice)


def _find_test_blocks_brace(lines, test_func_re):
    blocks = []
    current_start = None
    brace_depth = 0
    seen_brace = False
    for i, line in enumerate(lines, 1):
        if test_func_re.search(line):
            if current_start is not None and not seen_brace:
                region = lines[current_start - 1 : i - 1]
                if not _is_annotation_block(region):
                    blocks.append((current_start, i - 1))
                    current_start = i
                    brace_depth = 0
            else:
                current_start = i
                brace_depth = 0
                seen_brace = False
        if current_start is not None:
            if "{" in line:
                seen_brace = True
            brace_depth += line.count("{") - line.count("}")
            if seen_brace and brace_depth <= 0:
                blocks.append((current_start, i))
                current_start = None
    if current_start is not None:
        blocks.append((current_start, len(lines)))
    return blocks


def _find_test_blocks_indent(lines, test_func_re):
    blocks = []
    current_start = None
    base_indent = 0
    for i, line in enumerate(lines, 1):
        if test_func_re.search(line):
            if current_start is not None:
                blocks.append((current_start, i - 1))
            current_start = i
            base_indent = len(line) - len(line.lstrip())
        elif current_start is not None:
            stripped = line.lstrip()
            if stripped and (len(line) - len(stripped)) <= base_indent:
                blocks.append((current_start, i - 1))
                current_start = None
    if current_start is not None:
        blocks.append((current_start, len(lines)))
    return blocks


# ---------------------------------------------------------------------------
# Pattern verification — model declares, script checks structure
# ---------------------------------------------------------------------------

_UI_SETUP_RE = re.compile(
    r"\bsetContent\b|\bcreateComposeRule\b|\bcreateAndroidComposeRule\b"
    r"|\btestWidgets\b|\bXCUIApplication\b|\bpumpWidget\b",
    re.I,
)
_UI_SETUP_JS_RE = re.compile(r"\brender\s*\(", re.I)

_VALID_PATTERNS = {"ui-interaction", "value-assertion", "error-handling", "snapshot"}


def _verify_pattern(pattern, block_text, cfg, has_literal_eq, lang=None):
    """Verify the model-declared pattern against structural requirements.

    Returns None if OK, or a string describing what's missing.
    """
    if pattern not in _VALID_PATTERNS:
        return (
            f"unknown pattern '{pattern}', "
            f"must be one of: {', '.join(sorted(_VALID_PATTERNS))}"
        )

    if pattern == "ui-interaction":
        missing = []
        has_setup = bool(_UI_SETUP_RE.search(block_text))
        if lang in ("js", "ts"):
            has_setup = has_setup or bool(_UI_SETUP_JS_RE.search(block_text))
        if not has_setup:
            missing.append("UI setup (setContent/render/pumpWidget)")
        da = cfg.get("device_action")
        if not da or not da.search(block_text):
            missing.append("device action (tap/click/type/swipe)")
        uq = cfg.get("ui_state_query")
        if not uq or not uq.search(block_text):
            missing.append("UI state assertion (assertIsDisplayed/find)")
        if missing:
            return "missing " + ", ".join(missing)
        return None

    if pattern == "value-assertion":
        if not has_literal_eq:
            return "no assertEquals/expect with literal expected value"
        return None

    if pattern == "error-handling":
        if not cfg["error_assert"].search(block_text):
            return "no assertThrows/assertFailsWith/shouldThrow call"
        return None

    if pattern == "snapshot":
        snap = cfg.get("snapshot_assert")
        if not snap or not snap.search(block_text):
            return "no snapshot/golden comparison call"
        return None


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_file(path, lang=None):
    path = Path(path)
    if lang is None:
        lang = _EXT_TO_LANG.get(path.suffix)
    if lang is None:
        return []

    cfg = _lang_config(lang)
    violations = []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    if cfg["block_delim"] == "indent":
        blocks = _find_test_blocks_indent(lines, cfg["test_func"])
    else:
        blocks = _find_test_blocks_brace(lines, cfg["test_func"])

    prev_end = 0
    for start, end in blocks:
        block_text = "\n".join(lines[start - 1 : end])

        # Rule 1: no assertion
        has_assert = any(p.search(block_text) for p in cfg["assert_any"])
        if not has_assert:
            violations.append(Violation(
                path, start, "no-assertion",
                f"test at line {start} has no assertion",
            ))
            prev_end = end
            continue

        # Track has_literal_eq: any assertEquals-like call where the expected
        # arg is NOT a SUT call (lowercaseVar.method).
        has_literal_eq = False
        if lang in ("js", "ts"):
            for m in _JS_CHAINED.finditer(block_text):
                expected = m.group(2).strip()
                if not _SUT_CALL.match(expected):
                    has_literal_eq = True
        for m in _ASSERTTHAT_CHAINED.finditer(block_text):
            expected = m.group(2).strip()
            if not _SUT_CALL.match(expected):
                has_literal_eq = True
        eq_open = cfg["assert_eq_open"]
        for m in eq_open.finditer(block_text):
            if cfg["expected_pos"] == "first":
                val = _extract_arg(block_text, m.end())
            else:
                d, j = 1, m.end()
                while j < len(block_text) and d > 0:
                    if block_text[j] == "(": d += 1
                    elif block_text[j] == ")": d -= 1
                    elif block_text[j] == "," and d == 1:
                        val = _extract_arg(block_text, j + 1)
                        break
                    j += 1
                else:
                    continue
            if not val:
                continue
            if not _SUT_CALL.match(val):
                has_literal_eq = True

        _ui_re = cfg.get("ui_assert")
        _has_ui = bool(_ui_re and _ui_re.search(block_text))
        _has_value = bool(cfg["value_assert"].search(block_text))

        # Rule 3: asserting on mock variable
        mock_decl = cfg["mock_decl"]
        mock_vars = {m.group(1) for m in mock_decl.finditer(block_text)}
        for var in mock_vars:
            for p in cfg["assert_any"]:
                for m in p.finditer(block_text):
                    if block_text.startswith('verify', m.start()):
                        continue
                    k = m.end()
                    j = -1
                    if k > 0 and block_text[k - 1] in '({':
                        depth, j = 1, k
                        while j < len(block_text) and depth > 0:
                            ch = block_text[j]
                            if ch in '({': depth += 1
                            elif ch in ')}': depth -= 1
                            j += 1
                        if depth > 0:
                            j = -1
                    if j < 0:
                        j = block_text.find("\n", m.start())
                        if j < 0:
                            j = len(block_text)
                    segment = block_text[m.start():j]
                    if re.search(r"\b" + re.escape(var) + r"\b", segment):
                        line_offset = block_text[: m.start()].count("\n")
                        violations.append(Violation(
                            path, start + line_offset, "mock-assert",
                            f"assertion references mock variable '{var}'",
                        ))

        # Rule 4: callback counter
        counters = {m.group(1) for m in cfg["counter_decl"].finditer(block_text)}
        incremented = {m.group(1) for m in cfg["counter_inc"].finditer(block_text)}
        counter_vars = counters & incremented
        for var in counter_vars:
            tpl = cfg["counter_assert"]
            pat = re.compile(tpl.replace("{var}", re.escape(var)))
            for m in pat.finditer(block_text):
                line_offset = block_text[: m.start()].count("\n")
                violations.append(Violation(
                    path, start + line_offset, "callback-counter",
                    f"assertion only verifies callback count '{var}', "
                    f"not behavioral outcome",
                ))

        # Rule A2: callback flag — var ok=false; ...{ok=true}; assertTrue(ok)
        # Runs before A3 so flag-caught vars can be excluded from capture
        flag_caught = set()
        cb_assign_re = cfg["callback_assign"]
        cb_assigned = set()
        for m in cb_assign_re.finditer(block_text):
            for g in m.groups():
                if g:
                    cb_assigned.add(g)
        flag_vars = {m.group(1) for m in cfg["flag_decl"].finditer(block_text)}
        flag_vars -= counter_vars
        flag_vars &= cb_assigned
        for m in cfg["flag_assert"].finditer(block_text):
            var = m.group(1) or (m.group(2) if m.lastindex >= 2 else None)
            if var and var in flag_vars:
                flag_caught.add(var)
                line_offset = block_text[: m.start()].count("\n")
                violations.append(Violation(
                    path, start + line_offset, "callback-flag",
                        f"assertion on callback flag '{var}' "
                        f"(boolean set in callback, not observable state)",
                    ))

        # Rule A3: callback-capture
        cb_vars = {m.group(1) for m in cfg["var_decl"].finditer(block_text)}
        capture_vars = (cb_vars & cb_assigned) - counter_vars - flag_caught
        if capture_vars:
            actual_re = cfg["actual_in_eq"]
            for m in actual_re.finditer(block_text):
                actual_var = m.group(1)
                if actual_var in capture_vars:
                    line_offset = block_text[: m.start()].count("\n")
                    msg = (
                        f"assertion on callback-captured variable "
                        f"'{actual_var}', not observable state"
                    )
                    if not _has_ui:
                        msg += " (test has zero UI assertions)"
                    violations.append(Violation(
                        path, start + line_offset, "callback-capture", msg,
                    ))

        # Rule A4: callback collect — list=[];...{list.add()};assertEquals([...],list)
        coll_vars = {m.group(1) for m in cfg["collect_decl"].finditer(block_text)}
        mutated = {m.group(1) for m in cfg["collect_mutate"].finditer(block_text)}
        collect_vars = coll_vars & mutated
        actual_re = cfg["actual_in_eq"]
        for var in collect_vars:
            for m in actual_re.finditer(block_text):
                if m.group(1) == var:
                    line_offset = block_text[: m.start()].count("\n")
                    violations.append(Violation(
                        path, start + line_offset, "callback-collect",
                        f"assertion on callback-collected variable "
                        f"'{var}', not observable state",
                    ))

        # Rule B2: verify-only — verify(mock).method() without value assertion
        verify_only_re = cfg.get("verify_only")
        if verify_only_re and verify_only_re.search(block_text):
            if not _has_value and not _has_ui:
                violations.append(Violation(
                    path, start, "verify-only",
                    "test only verifies mock was called, "
                    "no assertion on output or state",
                ))

        # Rule D2: weak assertion — only assertNotNull/isNotEmpty/assertIs
        if cfg["weak_assert"].search(block_text) and not _has_value and not _has_ui:
            violations.append(Violation(
                path, start, "weak-assertion",
                "test only uses weak assertions "
                "(assertNotNull/isNotEmpty/assertIs), "
                "no value equality check",
            ))

        # Rule E1: verify order — verifyOrder { a(); b() }
        vo_re = cfg.get("verify_order")
        if vo_re and vo_re.search(block_text):
            violations.append(Violation(
                path, start, "verify-order",
                "test asserts on call order "
                "(implementation coupling)",
            ))

        # Rule E2: verify count — verify(exactly=N) / toHaveBeenCalledTimes
        vc_re = cfg.get("verify_count")
        if vc_re and vc_re.search(block_text):
            violations.append(Violation(
                path, start, "verify-count",
                "test asserts on exact call count "
                "(implementation coupling)",
            ))

        # Rule F (allowlist): UI test must have device action + UI state query
        # Skip for blocks declaring ui-interaction — Rule G handles it
        _pre = max(prev_end, start - 4)
        search_text = "\n".join(lines[_pre : end])
        _is_ui_annotated = bool(re.search(
            r'@test-pattern:\s*ui-interaction\b',
            search_text,
        ))
        da = cfg.get("device_action")
        uq = cfg.get("ui_state_query")
        if da and uq and not _is_ui_annotated:
            has_ui_setup = bool(_UI_SETUP_RE.search(block_text))
            if lang in ("js", "ts"):
                has_ui_setup = has_ui_setup or bool(_UI_SETUP_JS_RE.search(block_text))
            if has_ui_setup:
                has_device_action = bool(da.search(block_text))
                has_ui_query = bool(uq.search(block_text))
                if not has_device_action:
                    violations.append(Violation(
                        path, start, "no-device-action",
                        "UI test has no device action "
                        "(tap/click/type/swipe)",
                    ))
                if not has_ui_query:
                    violations.append(Violation(
                        path, start, "no-ui-query",
                        "UI test has no UI state assertion "
                        "(assertIsDisplayed/find/exists)",
                    ))

        # Rule G: model-declared pattern — every test must declare
        # @test-pattern: <name>, then the script verifies structurally
        # Look in block + up to 3 lines before (annotation may precede @Test)
        pattern_m = re.search(
            r"(?://|#)\s*@test-pattern:\s*(\S+)", search_text,
        )
        if not pattern_m:
            violations.append(Violation(
                path, start, "unclassified",
                "test has no @test-pattern annotation "
                "(must declare: ui-interaction / value-assertion / "
                "error-handling / snapshot)",
            ))
        else:
            pattern = pattern_m.group(1)
            pv = _verify_pattern(pattern, block_text, cfg, has_literal_eq, lang)
            if pv:
                violations.append(Violation(
                    path, start, "pattern-mismatch",
                    f"@test-pattern: {pattern} — {pv}",
                ))

        prev_end = end

    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def lint(target, as_json=False):
    target = Path(target)
    files = (
        sorted(target.rglob("*"))
        if target.is_dir()
        else [target]
    )
    files = [f for f in files if f.is_file() and f.suffix in _EXT_TO_LANG]

    all_violations = []
    for f in files:
        all_violations.extend(check_file(f))

    if as_json:
        print(json.dumps(
            {"violations": [v.to_dict() for v in all_violations],
             "files_checked": len(files)},
            indent=2, ensure_ascii=False,
        ))
    else:
        for v in all_violations:
            print(f"{v.file}:{v.line}: [{v.rule}] {v.message}")
        if not all_violations:
            print(f"OK — {len(files)} file(s), 0 violations")

    return all_violations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test code quality lint")
    parser.add_argument("target", help="test file or directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    violations = lint(args.target, args.json)
    sys.exit(1 if violations else 0)
