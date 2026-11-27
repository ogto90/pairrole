"""Skills entries in both CV layouts, and domain rules for long-form capability names."""

from matching.candidate_profile import EvidenceOrigin, representative_profile
from matching.cv_normalizer import (
    ExtractedCapability,
    augment_explicit_skill_capabilities,
    extracted_from_profile,
    normalize_extracted_profile,
)
from matching.cv_skills_latex import explicit_skill_rows, split_skill_entries
from matching.domains.cybersecurity import CYBERSECURITY_DOMAIN
from matching.tailored_cv import sanitize_latex_source
from matching.tailored_cv_diff import extract_cv_units

PLAIN_LIST_CV = r"""
\begin{document}
\section*{Experience}
\begin{itemize}
\item \textbf{Ran:} the SAST rollout for 40 repositories.
\end{itemize}
\section*{Skills}
\begin{itemize}
\item \textbf{Application security:} Secure SDLC, SAST, SCA, DAST, OWASP Top 10.
\item \textbf{Engineering:} Python, GitLab CI/CD; TypeScript (personal project, hobby).
\item \textbf{Tools \& platforms:} Tenable.sc, Black Duck
\end{itemize}
\section*{Languages}
English
\end{document}
"""


def test_plain_list_skills_rows_are_found_only_in_skills_section():
    rows = explicit_skill_rows(PLAIN_LIST_CV)
    assert rows == [
        ("Application security", ["Secure SDLC", "SAST", "SCA", "DAST", "OWASP Top 10"]),
        ("Engineering", ["Python", "GitLab CI/CD", "TypeScript (personal project, hobby)"]),
        ("Tools & platforms", ["Tenable.sc", "Black Duck"]),
    ]


def test_skillrow_layout_is_unchanged():
    rows = explicit_skill_rows(r"\skillrow{Application \& Product Security}{Threat Modeling, SAST, SCA}")
    assert rows == [("Application \\& Product Security", ["Threat Modeling", "SAST", "SCA"])]


def test_split_ignores_separators_inside_parentheses():
    assert split_skill_entries("A (x, y; z), B; C") == ["A (x, y; z)", " B", " C"]


def test_plain_list_skills_reach_normalization_as_skills_only():
    extracted = augment_explicit_skill_capabilities(extracted_from_profile(representative_profile()), PLAIN_LIST_CV)
    names = {item.normalized_name.casefold() for item in extracted.capabilities}
    assert {"secure sdlc", "owasp top 10", "gitlab ci/cd", "tenable.sc", "black duck"} <= names
    added = [item for item in extracted.evidence_provenance if item.id.startswith("skills-")]
    assert added and all(item.origin == EvidenceOrigin.SKILLS for item in added)
    assert not any("ran" == item.cv_text.casefold() for item in added)


def test_tailoring_strips_annotations_from_plain_list_skills_only():
    source = (
        "\\section*{Experience}\n\\begin{itemize}\n"
        "\\item \\textbf{Led:} SAST work (professional evidence)\n\\end{itemize}\n"
        "\\section*{Skills}\n\\begin{itemize}\n"
        "\\item \\textbf{Application security:} SAST (skills-level), SCA (evidence level)\n"
        "\\item \\textbf{Tools:} Coverity\n\\end{itemize}\n"
    )
    cleaned = sanitize_latex_source(source)
    assert "\\item \\textbf{Application security:} SAST, SCA\n\\item \\textbf{Tools:} Coverity" in cleaned
    # Outside Skills, text is left alone.
    assert "SAST work (professional evidence)" in cleaned


def test_diff_labels_plain_list_skills_rows_as_skills():
    units = extract_cv_units(PLAIN_LIST_CV)
    skills = [unit for unit in units if unit.section == "Skills"]
    assert skills and all(unit.kind == "skill" for unit in skills)
    assert skills[0].text.startswith("Application security: Secure SDLC")
    experience = [unit for unit in units if unit.section == "Experience"]
    assert experience and all(unit.kind == "bullet" for unit in experience)


def _with_capability(name, refs):
    extracted = extracted_from_profile(representative_profile())
    extracted.capabilities.append(
        ExtractedCapability(normalized_name=name, category="application security", evidence_refs=refs)
    )
    return extracted


def test_long_form_dast_name_does_not_inherit_generic_web_scanning_evidence():
    extracted = _with_capability(
        "Dynamic application security testing (DAST)", ["historical-web-application-scanning"]
    )
    profile = normalize_extracted_profile(extracted, 2, domain_rules=CYBERSECURITY_DOMAIN)
    assert not any(item.normalized_name.startswith("Dynamic application") for item in profile.capabilities)


def test_combined_atomic_names_are_left_to_generic_normalization():
    extracted = _with_capability("SAST and DAST tooling", ["historical-web-application-scanning"])
    profile = normalize_extracted_profile(extracted, 2, domain_rules=CYBERSECURITY_DOMAIN)
    assert any(item.normalized_name == "SAST and DAST tooling" for item in profile.capabilities)


def test_profile_upload_parses_with_cybersecurity_domain_rules(monkeypatch):
    import ui.profile as profile_ui

    calls = []
    monkeypatch.setattr(profile_ui, "parse_candidate_profile", lambda *args, **kwargs: calls.append((args, kwargs)))
    profile_ui._parse_uploaded_cv("cv", 7)
    assert calls == [(("cv", 7), {"domain_rules": CYBERSECURITY_DOMAIN})]
