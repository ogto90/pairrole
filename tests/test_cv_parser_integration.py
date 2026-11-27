import os
import re
from pathlib import Path

import pytest

from matching.cv_parser import parse_candidate_profile

# Model output names capabilities in varying forms ("SAST" vs "Static application
# security testing (SAST)", "AWS" vs "AWS security"), so match on whole-word
# aliases rather than exact strings. Aliases mirror matching/job_evaluation.py.
REQUIRED_CAPABILITIES = {
    "vulnerability management": ("vulnerability management",),
    "sast": ("sast", "static application security testing"),
    "sca": ("sca", "software composition analysis"),
    "threat modeling": ("threat modeling", "threat modelling"),
    "secure code review": ("secure code review",),
    "aws": ("aws", "amazon web services"),
    "container security": ("container security",),
    "security automation": ("security automation",),
    "web application scanning": ("web application scanning", "dast", "dynamic application security testing"),
}


def _matching(capabilities, aliases):
    patterns = [re.compile(rf"\b{re.escape(alias)}\b") for alias in aliases]
    return [item for item in capabilities if any(p.search(item.normalized_name.casefold()) for p in patterns)]


@pytest.mark.integration
def test_parse_canonical_cv_with_openai():
    """Opt-in smoke test: RUN_OPENAI_CV_PARSER=1 pytest -m integration."""

    if os.getenv("RUN_OPENAI_CV_PARSER") != "1":
        pytest.skip("Set RUN_OPENAI_CV_PARSER=1 to spend one OpenAI API call")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")

    # Synthetic, committed fixture: the real cv/ folder is gitignored private data.
    cv_path = Path(__file__).parent / "fixtures" / "synthetic_security_cv.tex"
    profile = parse_candidate_profile(cv_path.read_text(encoding="utf-8"), 2)
    names = sorted(item.normalized_name for item in profile.capabilities)
    found = {key: _matching(profile.capabilities, aliases) for key, aliases in REQUIRED_CAPABILITIES.items()}

    missing = [key for key, items in found.items() if not items]
    assert not missing, f"parser omitted required inspection capabilities: {missing}; got {names}"

    assert max(item.evidence_level for item in found["vulnerability management"]) >= 3
    # The fixture limits AWS and container work to certifications and a home lab.
    for key in ("aws", "container security"):
        assert all(item.production_experience is False for item in found[key]), (
            f"{key} was credited as production experience: {found[key]}"
        )
