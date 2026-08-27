#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from test_lint import check_file


def _write(code: str, suffix=".kt") -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(code)
    f.flush()
    return Path(f.name)


def _rules(violations, rule):
    return [v for v in violations if v.rule == rule]


# ── Kotlin ──────────────────────────────────────────────────────────────────

class TestKotlinNoAssertion(unittest.TestCase):
    def test_flags(self):
        p = _write("class T { @Test fun t() { val x = f() } }")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 1)

    def test_passes(self):
        p = _write('class T { @Test fun t() { assertEquals("a", b) } }')
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 0)


class TestKotlinHasLiteralEq(unittest.TestCase):
    """computed-expected removed; value-assertion pattern catches SUT calls."""

    def test_sut_call_not_literal(self):
        """vm.get() as expected → value-assertion pattern should mismatch."""
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test fun t() { assertEquals(vm.get(), r) }
}
""")
        vs = _rules(check_file(p), "pattern-mismatch")
        self.assertEqual(len(vs), 1)
        self.assertIn("literal", vs[0].message)

    def test_literal_passes(self):
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test fun t() { assertEquals("ok", r) }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_constructor_passes(self):
        """UiText.Resource(...) is test data, not SUT."""
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test fun t() { assertEquals(UiText.Resource(R.string.x), r) }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_empty_list_generic_passes(self):
        """emptyList<String>() is test data."""
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test fun t() { assertEquals(emptyList<String>(), r) }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)


class TestKotlinMockAssert(unittest.TestCase):
    def test_flags(self):
        p = _write('class T { @Test fun t() { val s = mockk<S>(); assertEquals(1, s.c) } }')
        self.assertEqual(len(_rules(check_file(p), "mock-assert")), 1)


class TestKotlinCallbackCounter(unittest.TestCase):
    def test_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        var picks = 0
        setup { picks++ }
        btn.click()
        assertEquals(1, picks)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 1)

    def test_passes_non_counter(self):
        p = _write("""
class T {
    @Test fun t() {
        var s = ""
        setup { s = "ok" }
        assertEquals("ok", s)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 0)


class TestKotlinCallbackCapture(unittest.TestCase):
    def test_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        var selected = ""
        C(onSelect = { selected = it })
        assertEquals("ok", selected)
    }
}
""")
        vs = _rules(check_file(p), "callback-capture")
        self.assertEqual(len(vs), 1)
        self.assertIn("selected", vs[0].message)

    def test_marks_zero_ui(self):
        p = _write("""
class T {
    @Test fun t() {
        var result = ""
        C(onDone = { result = it })
        assertEquals("done", result)
    }
}
""")
        vs = _rules(check_file(p), "callback-capture")
        self.assertIn("zero UI assertions", vs[0].message)


# ── Java ────────────────────────────────────────────────────────────────────

class TestJava(unittest.TestCase):
    def test_no_assertion(self):
        p = _write("class T { @Test public void t() { int x = f(); } }", ".java")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 1)

    def test_sut_call_value_assertion_mismatch(self):
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test public void t() { assertEquals(vm.get(), r); }
}
""", ".java")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 1)

    def test_literal_value_assertion_passes(self):
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test public void t() { assertEquals("ok", r); }
}
""", ".java")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_mock_assert(self):
        p = _write('class T { @Test public void t() { var s = mock(S.class); assertEquals(1, s.c); } }', ".java")
        self.assertEqual(len(_rules(check_file(p), "mock-assert")), 1)

    def test_callback_counter(self):
        p = _write("""
class T {
    @Test public void t() {
        int count = 0;
        btn.setOnClick(v -> count++);
        assertEquals(1, count);
    }
}
""", ".java")
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 1)


# ── Dart ────────────────────────────────────────────────────────────────────

class TestDart(unittest.TestCase):
    def test_no_assertion(self):
        p = _write("test('t', () { var x = f(); });", ".dart")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 1)

    def test_sut_call_value_assertion_mismatch(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () { expect(actual, vm.compute()); });
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 1)

    def test_literal_value_assertion_passes(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () { expect(actual, 42); });
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_callback_counter(self):
        p = _write("""
test('t', () {
  var count = 0;
  btn.onTap = () { count++; };
  expect(count, 1);
});
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 1)


# ── Swift ───────────────────────────────────────────────────────────────────

class TestSwift(unittest.TestCase):
    def test_no_assertion(self):
        p = _write("func testFoo() { let x = f() }", ".swift")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 1)

    def test_sut_call_value_assertion_mismatch(self):
        p = _write("""
// @test-pattern: value-assertion
func testFoo() { XCTAssertEqual(result, vm.compute()) }
""", ".swift")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 1)

    def test_literal_value_assertion_passes(self):
        p = _write("""
// @test-pattern: value-assertion
func testFoo() { XCTAssertEqual(result, "ok") }
""", ".swift")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_dot_enum_value_assertion_passes(self):
        p = _write("""
// @test-pattern: value-assertion
func testFoo() { XCTAssertEqual(result, .active) }
""", ".swift")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_callback_counter(self):
        p = _write("""
func testFoo() {
    var count = 0
    btn.onTap = { count += 1 }
    XCTAssertEqual(count, 1)
}
""", ".swift")
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 1)


# ── JS/TS ───────────────────────────────────────────────────────────────────

class TestJS(unittest.TestCase):
    def test_no_assertion(self):
        p = _write("test('t', () => { const x = f(); });", ".ts")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 1)

    def test_sut_call_value_assertion_mismatch(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () => { expect(x).toBe(vm.get()); });
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 1)

    def test_literal_value_assertion_passes(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () => { expect(x).toBe(42); });
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_mock_assert(self):
        p = _write("test('t', () => { let fn = jest.fn(); expect(fn).toBe(1); });", ".ts")
        self.assertEqual(len(_rules(check_file(p), "mock-assert")), 1)

    def test_callback_counter(self):
        p = _write("""
test('t', () => {
    let count = 0;
    btn.onClick = () => { count++; };
    expect(count).toBe(1);
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 1)


# ── Allowlist (cross-language) ──────────────────────────────────────────────

class TestAllowlistKotlin(unittest.TestCase):
    def test_flags_no_device_action(self):
        p = _write("""
class T {
    @Test fun t() {
        composeRule.setContent { Text("hello") }
        composeRule.onNodeWithText("hello").assertIsDisplayed()
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 1)

    def test_passes_with_perform_click(self):
        p = _write("""
class T {
    @Test fun t() {
        composeRule.setContent { Button(onClick = {}) { Text("go") } }
        composeRule.onNodeWithText("go").performClick()
        composeRule.onNodeWithText("done").assertIsDisplayed()
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 0)

    def test_passes_with_trailing_lambda(self):
        p = _write("""
class T {
    @Test fun t() {
        composeRule.setContent { Box() }
        composeRule.onNodeWithTag("x").performTouchInput { swipe(a, b) }
        composeRule.onNodeWithTag("x").assertIsDisplayed()
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 0)

    def test_flags_no_ui_query(self):
        p = _write("""
class T {
    @Test fun t() {
        var x = ""
        composeRule.setContent { C(onDone = { x = it }) }
        composeRule.onNodeWithText("go").performClick()
        assertEquals("ok", x)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-ui-query")), 1)

    def test_passes_with_ui_assert(self):
        p = _write("""
class T {
    @Test fun t() {
        composeRule.setContent { Text("hello") }
        composeRule.onNodeWithText("go").performClick()
        composeRule.onNodeWithText("done").assertIsDisplayed()
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-ui-query")), 0)


# ── New anti-patterns (A2, A4, B2, D2, E1, E2) ────────────────────────────

class TestCallbackFlag(unittest.TestCase):
    def test_kotlin_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        var called = false
        onResult = { called = true }
        assertTrue(called)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "callback-flag")), 1)

    def test_kotlin_passes_when_not_flag(self):
        p = _write("""
class T {
    @Test fun t() {
        var result = false
        vm.compute()
        assertEquals(true, result)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "callback-flag")), 0)

    def test_swift_flags(self):
        p = _write("""
func testFoo() {
    var done = false
    btn.onTap = { done = true }
    XCTAssertTrue(done)
}
""", ".swift")
        self.assertEqual(len(_rules(check_file(p), "callback-flag")), 1)

    def test_js_flags(self):
        p = _write("""
test('t', () => {
    let called = false;
    btn.onClick = () => { called = true; };
    expect(called).toBeTruthy();
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "callback-flag")), 1)


class TestCallbackCollect(unittest.TestCase):
    def test_kotlin_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        var items = mutableListOf()
        C(onAdd = { items.add(it) })
        assertEquals(listOf("a"), items)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "callback-collect")), 1)

    def test_js_flags(self):
        p = _write("""
test('t', () => {
    let items = [];
    btn.onSelect = (v) => { items.push(v); };
    expect(items).toBe([1]);
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "callback-collect")), 1)

    def test_swift_flags(self):
        p = _write("""
func testFoo() {
    var results = []
    sut.onResult = { results.append($0) }
    XCTAssertEqual(results, ["a"])
}
""", ".swift")
        self.assertEqual(len(_rules(check_file(p), "callback-collect")), 1)


class TestVerifyOnly(unittest.TestCase):
    def test_kotlin_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        val repo = mockk<Repo>()
        vm.save()
        verify { repo.save(any()) }
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "verify-only")), 1)

    def test_kotlin_passes_with_eq(self):
        p = _write("""
class T {
    @Test fun t() {
        val repo = mockk<Repo>()
        vm.save()
        verify { repo.save(any()) }
        assertEquals("ok", vm.status)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "verify-only")), 0)

    def test_js_flags(self):
        p = _write("""
test('t', () => {
    let fn = jest.fn();
    sut.run();
    expect(fn).toHaveBeenCalled();
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "verify-only")), 1)


class TestWeakAssertion(unittest.TestCase):
    def test_kotlin_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        val result = vm.getData()
        assertNotNull(result)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "weak-assertion")), 1)

    def test_kotlin_passes_with_eq(self):
        p = _write("""
class T {
    @Test fun t() {
        val result = vm.getData()
        assertNotNull(result)
        assertEquals("ok", result.name)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "weak-assertion")), 0)

    def test_dart_flags(self):
        p = _write("""
test('t', () {
  final result = vm.getData();
  expect(result, isNotNull);
});
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "weak-assertion")), 1)

    def test_js_flags(self):
        p = _write("""
test('t', () => {
    const result = sut.run();
    expect(result).toBeDefined();
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "weak-assertion")), 1)


class TestVerifyOrder(unittest.TestCase):
    def test_kotlin_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        vm.process()
        verifyOrder { repo.validate(); repo.save() }
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "verify-order")), 1)


class TestVerifyCount(unittest.TestCase):
    def test_kotlin_flags(self):
        p = _write("""
class T {
    @Test fun t() {
        vm.load()
        verify(exactly = 1) { repo.get() }
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "verify-count")), 1)

    def test_js_flags(self):
        p = _write("""
test('t', () => {
    sut.run();
    expect(fn).toHaveBeenCalledTimes(2);
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "verify-count")), 1)


class TestAllowlistDart(unittest.TestCase):
    def test_flags_no_device_action(self):
        p = _write("""
testWidgets('t', (tester) async {
  await tester.pumpWidget(MyApp());
  expect(find.text('hello'), findsOneWidget);
});
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 1)

    def test_passes_with_tap(self):
        p = _write("""
testWidgets('t', (tester) async {
  await tester.pumpWidget(MyApp());
  await tester.tap(find.byKey(Key('btn')));
  expect(find.text('done'), findsOneWidget);
});
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 0)


class TestAllowlistJS(unittest.TestCase):
    def test_flags_no_device_action(self):
        p = _write("""
test('t', () => {
  render(<App />);
  expect(screen.getByText('hello')).toBeInTheDocument();
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 1)

    def test_passes_with_click(self):
        p = _write("""
test('t', () => {
  render(<App />);
  fireEvent.click(screen.getByText('go'));
  expect(screen.getByText('done')).toBeInTheDocument();
});
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "no-device-action")), 0)


# ── Pattern classification (model-declared @test-pattern) ──────────────

class TestPatternUnclassified(unittest.TestCase):
    def test_no_annotation(self):
        p = _write('class T { @Test fun t() { assertEquals("a", b) } }')
        self.assertEqual(len(_rules(check_file(p), "unclassified")), 1)

    def test_with_annotation_no_unclassified(self):
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test fun t() { assertEquals("a", b) }
}
""")
        self.assertEqual(len(_rules(check_file(p), "unclassified")), 0)


class TestPatternMismatch(unittest.TestCase):
    def test_ui_interaction_missing_device_action(self):
        p = _write("""
class T {
    // @test-pattern: ui-interaction
    @Test fun t() {
        composeRule.setContent { Text("hi") }
        composeRule.onNodeWithText("hi").assertIsDisplayed()
    }
}
""")
        vs = _rules(check_file(p), "pattern-mismatch")
        self.assertEqual(len(vs), 1)
        self.assertIn("device action", vs[0].message)

    def test_ui_interaction_complete_passes(self):
        p = _write("""
class T {
    // @test-pattern: ui-interaction
    @Test fun t() {
        composeRule.setContent { Button(onClick={}) { Text("go") } }
        composeRule.onNodeWithText("go").performClick()
        composeRule.onNodeWithText("done").assertIsDisplayed()
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_error_handling_missing_throw(self):
        p = _write("""
class T {
    // @test-pattern: error-handling
    @Test fun t() { assertEquals("err", result) }
}
""")
        vs = _rules(check_file(p), "pattern-mismatch")
        self.assertEqual(len(vs), 1)
        self.assertIn("assertThrows", vs[0].message)

    def test_error_handling_passes(self):
        p = _write("""
class T {
    // @test-pattern: error-handling
    @Test fun t() { assertThrows<IllegalArgumentException> { vm.validate("") } }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_unknown_pattern(self):
        p = _write("""
class T {
    // @test-pattern: magic-test
    @Test fun t() { assertEquals("a", b) }
}
""")
        vs = _rules(check_file(p), "pattern-mismatch")
        self.assertEqual(len(vs), 1)
        self.assertIn("unknown", vs[0].message)

    def test_dart_annotation(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () { expect(actual, 42); });
""", ".dart")
        self.assertEqual(len(_rules(check_file(p), "unclassified")), 0)
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_js_annotation(self):
        p = _write("""
// @test-pattern: error-handling
test('t', () => { expect(() => sut.run()).toThrow(); });
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_python_annotation(self):
        p = _write("""
# @test-pattern: error-handling
def test_foo(self):
    with self.assertRaises(ValueError):
        sut.validate("")
""", ".py")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)


class TestPatternPlusAntipattern(unittest.TestCase):
    """Pattern match + anti-pattern both fire — both must pass."""

    def test_value_assertion_with_callback_counter(self):
        p = _write("""
class T {
    // @test-pattern: value-assertion
    @Test fun t() {
        var picks = 0
        setup { picks++ }
        assertEquals(1, picks)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)
        self.assertEqual(len(_rules(check_file(p), "callback-counter")), 1)


class TestBlockDetection(unittest.TestCase):
    """Block detection edge cases: expression-body, multi-line signature."""

    def test_expression_body_detected(self):
        p = _write("""
class T {
    @Test fun a() = assertEquals(1, sut.price)
    @Test fun b() { assertEquals(2, sut.qty) }
}
""")
        vs = check_file(p)
        self.assertEqual(len(_rules(vs, "unclassified")), 2)

    def test_multi_line_signature(self):
        p = _write("""
class T {
    @Test
    @Config(sdk=[33])
    fun t() {
        assertEquals("ok", sut.result)
    }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 0)

    def test_annotation_inside_body_not_test_func(self):
        p = _write("""
class T {
    @Test fun t() {
        // @test-pattern: value-assertion
        assertEquals("ok", sut.result)
    }
}
""")
        vs = check_file(p)
        self.assertEqual(len(_rules(vs, "pattern-mismatch")), 0)
        self.assertEqual(len(_rules(vs, "no-assertion")), 0)


class TestKotlinGenericAssertions(unittest.TestCase):
    """Kotlin generic assertions: assertFailsWith<T>, assertIs<T>."""

    def test_assert_fails_with_generic_recognized(self):
        p = _write("""
class T {
    @Test fun t() { assertFailsWith<IllegalStateException> { sut.go() } }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 0)

    def test_assert_throws_generic_recognized(self):
        p = _write("""
class T {
    @Test fun t() { assertThrows<IllegalStateException> { sut.go() } }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 0)

    def test_error_handling_with_generic(self):
        p = _write("""
class T {
    // @test-pattern: error-handling
    @Test fun t() { assertFailsWith<IllegalArgumentException> { sut.validate("") } }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)


class TestKotlinTestExpected(unittest.TestCase):
    """@Test(expected=...) recognized as assertion and error-handling."""

    def test_expected_is_assertion(self):
        p = _write("""
class T {
    @Test(expected = IllegalArgumentException::class)
    fun rejectsBlank() { sut.submit("") }
}
""")
        self.assertEqual(len(_rules(check_file(p), "no-assertion")), 0)

    def test_expected_satisfies_error_handling(self):
        p = _write("""
class T {
    // @test-pattern: error-handling
    @Test(expected = IllegalArgumentException::class)
    fun rejectsBlank() { sut.submit("") }
}
""")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)


class TestJsPositionalAssertions(unittest.TestCase):
    """JS/TS assert.strictEqual should satisfy value-assertion."""

    def test_strict_equal_satisfies_value_assertion(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () => { assert.strictEqual(sut.get(), 'ok'); });
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 0)

    def test_strict_equal_sut_only_fails(self):
        p = _write("""
// @test-pattern: value-assertion
test('t', () => { assert.strictEqual(sut.get(), vm.state); });
""", ".ts")
        self.assertEqual(len(_rules(check_file(p), "pattern-mismatch")), 1)


if __name__ == "__main__":
    unittest.main()
