import json

import pytest

import matching.tailored_cv as tailoring
from tests.latex_sandbox_support import bubblewrap_namespace_unavailable_reason


_BWRAP_NAMESPACE_REASON = bubblewrap_namespace_unavailable_reason()
requires_bubblewrap_namespaces = pytest.mark.skipif(
    _BWRAP_NAMESPACE_REASON is not None,
    reason=_BWRAP_NAMESPACE_REASON or "bubblewrap namespaces unavailable",
)


BROKEN_HEADER = r"""\documentclass{article}
\begin{document}
\begin{center}
$CYBER SECURITY MANAGER
\end{center}
Delivered security improvements worth $100.
\end{document}
"""


@requires_bubblewrap_namespaces
def test_cross_header_math_failure_is_reproduced_then_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(tailoring, "_COMPILATION_DIAGNOSTICS", tmp_path / "failures")
    with pytest.raises(tailoring.TailoredCVError, match=r"invalid in math mode"):
        tailoring.compile_latex(BROKEN_HEADER)
    sanitized = tailoring.sanitize_latex_source(BROKEN_HEADER)
    assert r"\$CYBER SECURITY MANAGER" in sanitized
    assert r"worth \$100" in sanitized
    assert tailoring.compile_latex(sanitized).startswith(b"%PDF-")
    assert tailoring.sanitize_latex_source(sanitized) == sanitized


def test_math_pairs_ignore_escaped_dollars_and_keep_valid_math():
    source = r"""\documentclass{article}
\begin{document}
Unmatched $ amount \$120.

Version $x_1$ and \(x_2\).
\end{document}
"""
    result = tailoring.sanitize_latex_source(source)
    assert r"Unmatched \$ amount \$120" in result
    assert r"$x_1$" in result and r"\(x_2\)" in result


def test_failure_preserves_exact_source_and_explicit_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(tailoring, "_COMPILATION_DIAGNOSTICS", tmp_path / "failures")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-do-not-save")
    def fail(source, *, diagnostics):
        diagnostics.update(compiler="lualatex", returncode=1, log="synthetic compiler error")
        raise tailoring.TailoredCVError("synthetic error")
    monkeypatch.setattr(tailoring, "_compile_latex_isolated", fail)
    with pytest.raises(tailoring.TailoredCVError, match="Offline debugging files"):
        tailoring.compile_latex(BROKEN_HEADER)
    directory, = (tmp_path / "failures").iterdir()
    assert (directory / "source.tex").read_text() == BROKEN_HEADER
    error = json.loads((directory / "error.json").read_text())
    assert error["returncode"] == 1
    assert "dummy-do-not-save" not in (directory / "error.json").read_text()
    assert (directory.stat().st_mode & 0o777) == 0o700
    assert ((directory / "source.tex").stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize("spacing", ["4pt", "-2mm", " .5em ", "+1.5ex"])
def test_header_spacing_with_missing_slash_is_repaired(spacing):
    source = (r"\documentclass{article}\begin{document}\begin{center}"
              + r"{Security Engineer}\[" + spacing + "]\n"
              + r"Contact details\end{center}\end{document}")
    result = tailoring.sanitize_latex_source(source)
    assert r"{Security Engineer}\\[" + spacing + "]" in result
    assert tailoring.sanitize_latex_source(result) == result


def test_display_math_and_existing_spacing_are_preserved():
    source = (r"\begin{document}Text\\[4pt]Next line"
              + r"\[x^2 + y^2 = z^2\]\end{document}")
    assert tailoring.sanitize_latex_source(source) == source
