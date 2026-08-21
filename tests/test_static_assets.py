"""Assets that are not Python, and therefore not covered by the rest of the suite.

Both checks here exist because something shipped broken. The UI's `<script>`
was syntactically invalid for several releases — the page rendered, so every
existing test passed, and asking a question silently did nothing. The Makefile
recipe contained the two characters backslash-n instead of a line continuation,
so the documented `make docker-run` passed them to docker as arguments.

Neither is exotic. Both come from writing escape sequences through a shell
heredoc, which is exactly the mistake a test can catch and review cannot.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "src" / "data_agent" / "entrypoints" / "ui" / "index.html"
MAKEFILE = REPO / "Makefile"


def script_body() -> str:
    match = re.search(r"<script>(.*?)</script>", UI.read_text(encoding="utf-8"), re.S)
    assert match, "the UI has no <script> block"
    return match.group(1)


class TestAgentUi:
    def test_the_page_exists(self):
        assert UI.is_file()

    def test_the_script_has_no_unterminated_string_literal(self):
        """A cheap check that runs everywhere, even without node.

        A string literal broken across a real newline is what actually happened;
        counting unescaped quotes per line catches it without a JS parser.
        """
        for number, line in enumerate(script_body().splitlines(), 1):
            code = re.sub(r"//.*$", "", line)
            unescaped = len(re.findall(r'(?<!\\)"', code))
            assert unescaped % 2 == 0, f"unbalanced quote on script line {number}: {line!r}"

    @pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
    def test_the_script_parses(self, tmp_path):
        """The real check: hand it to a JavaScript engine."""
        js = tmp_path / "ui.js"
        js.write_text(script_body(), encoding="utf-8")
        result = subprocess.run(  # noqa: S603
            [shutil.which("node"), "--check", str(js)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_the_sse_delimiters_are_escape_sequences(self):
        """The specific regression: these were literal newlines in the source."""
        body = script_body()
        assert r'indexOf("\n\n")' in body
        assert r'split("\n")' in body

    def test_nothing_is_rendered_as_markup(self):
        body = script_body()
        for sink in ("innerHTML =", "innerHTML+=", "outerHTML =", "insertAdjacentHTML"):
            assert sink not in body


def outside_quotes(line: str) -> str:
    """The line with single- and double-quoted runs removed.

    Recipes legitimately contain escape sequences inside quotes: the help target
    hands a printf format to awk. Only an *unquoted* one is the bug.
    """
    return re.sub(r"'[^']*'|\"[^\"]*\"", "", line)


class TestMakefile:
    def test_no_recipe_has_an_unquoted_escape_sequence(self):
        r"""The regression: `\n` written where a line continuation was meant, so
        the shell receives it as two literal characters."""
        for number, line in enumerate(MAKEFILE.read_text(encoding="utf-8").splitlines(), 1):
            if not line.startswith("\t"):
                continue
            assert "\\n" not in outside_quotes(line), (
                f"unquoted escape sequence in recipe on line {number}: {line!r}"
            )

    @pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
    def test_every_documented_target_expands(self):
        """`make -n` parses each recipe and prints what would run without running
        it, which is enough to catch a mangled continuation."""
        targets = re.findall(r"^([a-z][a-z-]*):.*?##", MAKEFILE.read_text(encoding="utf-8"), re.M)
        assert targets, "no self-documented targets found"
        for target in targets:
            result = subprocess.run(  # noqa: S603
                [shutil.which("make"), "-n", target],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"make -n {target} failed: {result.stderr}"

    def test_the_docker_target_uses_real_continuations(self):
        """The specific target that shipped broken."""
        recipe = MAKEFILE.read_text(encoding="utf-8").split("docker-run:", 1)[1]
        recipe = recipe.split("\n\n", 1)[0]
        assert "\\n" not in outside_quotes(recipe)
        assert "DA_ALLOW_UNAUTHENTICATED=true" in recipe
