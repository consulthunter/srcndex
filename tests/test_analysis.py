"""Tests for analysis.py — endpoint detection, test classification, framework detection."""

from srcndx.analysis import classify_test, detect_endpoint, detect_test_framework
from srcndx.models import TestKind

# ---------------------------------------------------------------------------
# detect_test_framework
# ---------------------------------------------------------------------------

class TestDetectTestFramework:
    # Java
    def test_java_junit5(self):
        assert detect_test_framework(["org.junit.jupiter.api.Test"], "java") == "junit5"

    def test_java_junit4(self):
        assert detect_test_framework(["org.junit.Assert", "org.junit.Test"], "java") == "junit4"

    def test_java_junit5_beats_junit4(self):
        # jupiter import present alongside a plain org.junit import — must return junit5
        imports = ["org.junit.jupiter.api.Test", "org.junit.Before"]
        assert detect_test_framework(imports, "java") == "junit5"

    def test_java_testng(self):
        assert detect_test_framework(["org.testng.annotations.Test"], "java") == "testng"

    def test_java_cucumber(self):
        assert detect_test_framework(["io.cucumber.java.en.Given"], "java") == "cucumber"

    def test_java_no_match(self):
        assert detect_test_framework(["com.example.Service"], "java") is None

    # Python
    def test_python_pytest(self):
        assert detect_test_framework(["pytest"], "python") == "pytest"

    def test_python_pytest_submodule(self):
        assert detect_test_framework(["pytest.mark"], "python") == "pytest"

    def test_python_unittest(self):
        assert detect_test_framework(["unittest", "unittest.mock"], "python") == "unittest"

    def test_python_nose(self):
        assert detect_test_framework(["nose.tools"], "python") == "nose"

    def test_python_nose2(self):
        assert detect_test_framework(["nose2"], "python") == "nose"

    def test_python_no_match(self):
        assert detect_test_framework(["pathlib", "os"], "python") is None

    # C#
    def test_csharp_nunit(self):
        assert detect_test_framework(["NUnit.Framework"], "csharp") == "nunit"

    def test_csharp_xunit(self):
        assert detect_test_framework(["Xunit", "Xunit.Abstractions"], "csharp") == "xunit"

    def test_csharp_mstest(self):
        imports = ["Microsoft.VisualStudio.TestTools.UnitTesting"]
        assert detect_test_framework(imports, "csharp") == "mstest"

    def test_csharp_no_match(self):
        assert detect_test_framework(["System.Collections.Generic"], "csharp") is None

    # TypeScript / TSX
    def test_ts_jest_globals(self):
        assert detect_test_framework(["@jest/globals"], "typescript") == "jest"

    def test_ts_jest_types(self):
        assert detect_test_framework(["@types/jest"], "typescript") == "jest"

    def test_ts_vitest(self):
        assert detect_test_framework(["vitest"], "typescript") == "vitest"

    def test_ts_vitest_subpath(self):
        assert detect_test_framework(["vitest/config"], "typescript") == "vitest"

    def test_ts_playwright(self):
        assert detect_test_framework(["@playwright/test"], "typescript") == "playwright"

    def test_ts_cypress(self):
        assert detect_test_framework(["cypress"], "typescript") == "cypress"

    def test_ts_mocha(self):
        assert detect_test_framework(["mocha"], "typescript") == "mocha"

    def test_tsx_treated_same_as_ts(self):
        assert detect_test_framework(["vitest"], "tsx") == "vitest"

    def test_ts_no_match(self):
        assert detect_test_framework(["react", "react-dom"], "typescript") is None

    # Edge cases
    def test_unknown_language_returns_none(self):
        assert detect_test_framework(["some.import"], "kotlin") is None

    def test_empty_imports_returns_none(self):
        assert detect_test_framework([], "java") is None


# ---------------------------------------------------------------------------
# detect_endpoint (smoke — full coverage in parser tests)
# ---------------------------------------------------------------------------

class TestDetectEndpoint:
    def test_spring_get_mapping(self):
        is_ep, method, path = detect_endpoint(['@GetMapping("/users")'])
        assert is_ep is True
        assert method == "GET"
        assert path == "/users"

    def test_no_endpoint(self):
        is_ep, method, path = detect_endpoint(["@Override"])
        assert is_ep is False
        assert method is None
        assert path is None


# ---------------------------------------------------------------------------
# classify_test (smoke)
# ---------------------------------------------------------------------------

class TestClassifyTest:
    def test_e2e_dir(self):
        assert classify_test("tests/e2e/LoginFlow.java", []) == TestKind.E2E

    def test_integration_dir(self):
        assert classify_test("src/test/integration/UserIT.java", []) == TestKind.INTEGRATION

    def test_unit_default(self):
        assert classify_test("tests/unit/UserTest.java", []) == TestKind.UNIT

    def test_spring_boot_test_annotation(self):
        assert classify_test("src/test/UserTest.java", ["@SpringBootTest"]) == TestKind.INTEGRATION
