"""Locate explicit Skills entries in CV LaTeX, in both supported layouts.

Layouts:
  * template macro:  ``\\skillrow{Category}{Skill A, Skill B}``
  * plain list:      ``\\item \\textbf{Category:} Skill A, Skill B; Skill C.``
    (only inside a section whose heading mentions "skill")
"""

from __future__ import annotations

import re

SKILLROW_RE = re.compile(r"\\skillrow\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
SECTION_HEADING_RE = re.compile(r"\\(?:cvsection|section|subsection)\*?\{([^{}]*)\}")
# Group 1: the "\item \textbf{Category:}" prefix, group 2: category, group 3: entries.
SKILL_ITEM_RE = re.compile(
    r"(\\item\s*\\textbf\{([^{}]*)\}\s*:?)(.*?)(?=\\item\b|\\end\{itemize\}|\Z)",
    re.DOTALL,
)


def skills_section_spans(latex_text: str) -> list[tuple[int, int]]:
    """Return (start, end) offsets of every section body whose heading mentions skills."""

    headings = list(SECTION_HEADING_RE.finditer(latex_text))
    spans: list[tuple[int, int]] = []
    for index, heading in enumerate(headings):
        if "skill" not in heading.group(1).casefold():
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(latex_text)
        document_end = latex_text.find("\\end{document}", heading.end(), end)
        spans.append((heading.end(), document_end if document_end != -1 else end))
    return spans


def split_skill_entries(raw_entries: str) -> list[str]:
    """Split on commas/semicolons that are not inside parentheses."""

    entries: list[str] = []
    depth = 0
    current: list[str] = []
    for char in raw_entries:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        if char in ",;" and depth == 0:
            entries.append("".join(current))
            current = []
        else:
            current.append(char)
    entries.append("".join(current))
    return entries


def _clean(text: str) -> str:
    text = text.replace(r"\&", "&").replace(r"\%", "%")
    text = re.sub(r"\\[A-Za-z]+\*?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?", " ", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def explicit_skill_rows(latex_text: str) -> list[tuple[str, list[str]]]:
    """Return (category, entries) for every explicit Skills row, in document order."""

    rows: list[tuple[int, str, list[str]]] = []
    for match in SKILLROW_RE.finditer(latex_text):
        entries = [entry.replace(r"\&", "&").strip() for entry in match.group(2).split(",")]
        rows.append((match.start(), match.group(1), [entry for entry in entries if entry]))
    for start, end in skills_section_spans(latex_text):
        for match in SKILL_ITEM_RE.finditer(latex_text, start, end):
            category = _clean(match.group(2)).rstrip(":").strip()
            entries = [_clean(entry) for entry in split_skill_entries(match.group(3))]
            entries = [entry for entry in entries if entry]
            if category and entries:
                rows.append((match.start(), category, entries))
    rows.sort(key=lambda row: row[0])
    return [(category, entries) for _, category, entries in rows]
