"""Stateless symbol enrichment — endpoint detection, test classification,
and test framework detection.

Called by each parser at symbol-creation time; no AST access required,
only the already-collected annotations list, imports, and file path.
"""
from __future__ import annotations

import re

from srcndx.models import TestKind

# ---------------------------------------------------------------------------
# Endpoint detection
# ---------------------------------------------------------------------------

# More-specific prefixes must appear before less-specific ones so the first
# startswith() match wins (e.g. @GetMapping before @Get).
_ENDPOINT_PREFIXES: dict[str, str | None] = {
    # Spring Boot (Java) — stored with leading @
    "@GetMapping": "GET",
    "@PostMapping": "POST",
    "@PutMapping": "PUT",
    "@DeleteMapping": "DELETE",
    "@PatchMapping": "PATCH",
    "@RequestMapping": None,
    # NestJS (TypeScript) — stored with leading @
    "@Get(": "GET",
    "@Post(": "POST",
    "@Put(": "PUT",
    "@Delete(": "DELETE",
    "@Patch(": "PATCH",
    # FastAPI / Flask (Python) — Python parser strips leading @
    "app.get": "GET",
    "app.post": "POST",
    "app.put": "PUT",
    "app.delete": "DELETE",
    "app.patch": "PATCH",
    "app.route": None,
    "router.get": "GET",
    "router.post": "POST",
    "router.put": "PUT",
    "router.delete": "DELETE",
    "router.patch": "PATCH",
    # ASP.NET Core (C#) — stored without @ or []
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "Route": None,
}

_PATH_RE = re.compile(r'["\']([^"\']+)["\']')


def detect_endpoint(annotations: list[str]) -> tuple[bool, str | None, str | None]:
    """Return (is_endpoint, http_method, route_path) from a symbol's annotations."""
    for ann in annotations:
        for prefix, method in _ENDPOINT_PREFIXES.items():
            if ann.startswith(prefix):
                path: str | None = None
                m = _PATH_RE.search(ann)
                if m:
                    candidate = m.group(1)
                    if "/" in candidate or candidate.startswith("{"):
                        path = candidate
                return True, method, path
    return False, None, None


# ---------------------------------------------------------------------------
# Test classification
# ---------------------------------------------------------------------------

_E2E_DIR_SEGMENTS = frozenset({
    "e2e", "endtoend", "end-to-end", "functional",
    "acceptance", "smoke",
})
_INTEGRATION_DIR_SEGMENTS = frozenset({
    "integration", "integrationtest", "integration-test", "it",
})

# Annotation prefixes that signal integration or e2e tests.
_INTEGRATION_ANN_PREFIXES = (
    # Spring Boot
    "@SpringBootTest", "@IntegrationTest", "@DataJpaTest",
    "@WebMvcTest", "@DataMongoTest",
    # ASP.NET (stored without @)
    "Integration",
    # pytest
    "@pytest.mark.integration", "pytest.mark.integration",
)
_E2E_ANN_PREFIXES = (
    "@pytest.mark.e2e", "pytest.mark.e2e",
    "@pytest.mark.selenium", "pytest.mark.selenium",
    "@pytest.mark.playwright", "pytest.mark.playwright",
)


def classify_test(rel_path: str, annotations: list[str]) -> TestKind:
    """Return the test classification for a known-test symbol.

    Checks directory structure first (most reliable), then annotations.
    Defaults to UNIT if no stronger signal is present.
    """
    normalized = rel_path.lower().replace("\\", "/")
    segments = {s.strip("-_") for s in normalized.split("/")}

    if segments & _E2E_DIR_SEGMENTS:
        return TestKind.E2E
    if segments & _INTEGRATION_DIR_SEGMENTS:
        return TestKind.INTEGRATION

    for ann in annotations:
        if any(ann.startswith(p) for p in _E2E_ANN_PREFIXES):
            return TestKind.E2E
        if any(ann.startswith(p) for p in _INTEGRATION_ANN_PREFIXES):
            return TestKind.INTEGRATION

    return TestKind.UNIT


# ---------------------------------------------------------------------------
# Test framework detection
# ---------------------------------------------------------------------------

# Each entry is (import_substring, framework_name).  Checked in order; first
# match wins.  More-specific strings must come before less-specific ones
# (e.g. "org.junit.jupiter" before "org.junit").
_JAVA_FRAMEWORK_IMPORTS: list[tuple[str, str]] = [
    ("org.junit.jupiter", "junit5"),
    ("org.junit", "junit4"),
    ("org.testng", "testng"),
    ("io.cucumber", "cucumber"),
]

_PYTHON_FRAMEWORK_IMPORTS: list[tuple[str, str]] = [
    ("pytest", "pytest"),
    ("unittest", "unittest"),
    ("nose2", "nose"),
    ("nose", "nose"),
]

_CSHARP_FRAMEWORK_IMPORTS: list[tuple[str, str]] = [
    ("NUnit.Framework", "nunit"),
    ("Xunit", "xunit"),
    ("Microsoft.VisualStudio.TestTools", "mstest"),
]

_TS_FRAMEWORK_IMPORTS: list[tuple[str, str]] = [
    ("@jest/globals", "jest"),
    ("@types/jest", "jest"),
    ("jest", "jest"),
    ("vitest", "vitest"),
    ("@playwright/test", "playwright"),
    ("cypress", "cypress"),
    ("mocha", "mocha"),
    ("jasmine", "jasmine"),
]

_FRAMEWORK_MAP: dict[str, list[tuple[str, str]]] = {
    "java": _JAVA_FRAMEWORK_IMPORTS,
    "python": _PYTHON_FRAMEWORK_IMPORTS,
    "csharp": _CSHARP_FRAMEWORK_IMPORTS,
    "typescript": _TS_FRAMEWORK_IMPORTS,
    "tsx": _TS_FRAMEWORK_IMPORTS,
}


def detect_test_framework(imports: list[str], language: str) -> str | None:
    """Return the test framework name inferred from file-level imports.

    Returns None when no known framework import is found or the language
    is not recognised.  The enrichment layer can overwrite this with a
    higher-confidence signal from build files (pom.xml, .csproj, etc.).
    """
    candidates = _FRAMEWORK_MAP.get(language.lower())
    if not candidates:
        return None
    for imp in imports:
        for substring, framework in candidates:
            if substring in imp:
                return framework
    return None
