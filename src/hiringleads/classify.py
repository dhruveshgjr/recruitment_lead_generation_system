"""Deterministic role-family and skill classification.

The classifier is deliberately explainable. Every result carries evidence so a
recruiter can understand why a posting matched, and low-confidence predictions
can be sent to the review queue later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .normalize import clean_text
from .taxonomy import NEGATIVE_TITLE_PATTERNS, ROLE_FAMILIES, SKILL_PATTERNS, _SKILL_RE

_FAMILY_RE: dict[str, re.Pattern[str]] = {
    fam: re.compile(pattern, re.IGNORECASE) for fam, pattern in ROLE_FAMILIES.items()
}

_FAMILY_PRIORITY = [
    "security",
    "ml",
    "data_science",
    "data_engineering",
    "mobile",
    "sre",
    "devops",
    "embedded",
    "network",
    "qa",
    "frontend",
    "fullstack",
    "backend",
    "erp",
    "analytics",
    "design",
    "product",
    "management",
    "support",
]


@dataclass(slots=True)
class Classification:
    role_family: str | None
    confidence: float
    skills: list[str]
    seniority: str | None
    evidence: list[str]
    rejected: bool = False
    reject_reason: str | None = None


def _title_family_scores(title: str) -> tuple[dict[str, float], dict[str, str]]:
    scores: dict[str, float] = {}
    evidence: dict[str, str] = {}
    for fam, rx in _FAMILY_RE.items():
        m = rx.search(title)
        if not m:
            continue
        match = clean_text(m.group(0))
        specificity = min(1.0, len(match) / max(len(title), 1) * 3.0)
        scores[fam] = 1.0 + specificity
        evidence[fam] = match[:120]
    return scores, evidence


def _family_from_department(department: str | None) -> tuple[str | None, str | None]:
    if not department:
        return None, None
    dept = clean_text(department).lower()
    for fam in _FAMILY_PRIORITY:
        rx = _FAMILY_RE.get(fam)
        if rx and (m := rx.search(dept)):
            return fam, clean_text(m.group(0))[:120]
    return None, None


def extract_skills(title: str, description: str | None, *, max_skills: int = 25) -> list[str]:
    title = title or ""
    desc = (description or "")[:20000]

    weights: dict[str, float] = {}
    for skill, rx in _SKILL_RE.items():
        if rx.search(title):
            weights[skill] = weights.get(skill, 0.0) + 3.0
        if desc and rx.search(desc):
            weights[skill] = weights.get(skill, 0.0) + 1.0

    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    # Description-only technologies are legitimate skills. Title hits simply
    # receive more weight and therefore sort ahead of incidental body mentions.
    return [skill for skill, weight in ranked if weight >= 1.0][:max_skills]


def _family_from_skills(skills: list[str]) -> tuple[str | None, str | None]:
    s = set(skills)
    candidates = [
        ("devops", {"kubernetes", "terraform", "docker", "ansible", "helm", "cicd", "jenkins"}),
        ("ml", {"llm", "pytorch", "tensorflow", "mlops", "nlp", "computer_vision"}),
        ("data_engineering", {"spark", "airflow", "dbt", "snowflake", "databricks", "etl"}),
        ("frontend", {"react", "angular", "vue", "nextjs", "svelte"}),
        ("mobile", {"ios", "android", "react_native", "flutter"}),
        ("qa", {"selenium", "cypress", "playwright", "automation_testing"}),
        ("security", {"appsec", "pentest", "siem", "soc", "cloud_security"}),
        ("erp", {"salesforce", "servicenow", "workday", "sap", "dynamics"}),
        ("backend", {"python", "java", "go", "rust", "csharp", "nodejs", "django", "spring"}),
    ]
    for fam, skills_set in candidates:
        hit = sorted(s & skills_set)
        if hit:
            return fam, ", ".join(hit[:3])
    return None, None


def classify(
    title: str,
    description: str | None = None,
    department: str | None = None,
    seniority: str | None = None,
) -> Classification:
    title_clean = clean_text(title)
    if not title_clean:
        return Classification(None, 0.0, [], seniority, [], True, "empty_title")

    if NEGATIVE_TITLE_PATTERNS.search(title_clean):
        return Classification(None, 0.0, [], seniority, [], True, "negative_title")

    skills = extract_skills(title_clean, description)
    scores, evidence_by_family = _title_family_scores(title_clean)

    if not scores:
        fam, evidence = _family_from_department(department)
        if fam:
            return Classification(fam, 0.45, skills, seniority, [f"department:{evidence}"])
        fam, evidence = _family_from_skills(skills)
        if fam:
            return Classification(fam, 0.35, skills, seniority, [f"skills:{evidence}"])
        return Classification("other", 0.20, skills, seniority, [])

    best_score = max(scores.values())
    tied = [
        family for family, value in scores.items()
        if value >= best_score * 0.90
    ]
    best = min(
        tied,
        key=lambda family: _FAMILY_PRIORITY.index(family) if family in _FAMILY_PRIORITY else 99,
    )

    total = sum(scores.values())
    dominance = best_score / total if total else 0.0
    matched_len = len(evidence_by_family.get(best, ""))
    specificity = min(1.0, matched_len / max(len(title_clean), 1) * 3.0)
    confidence = round(dominance * (0.50 + 0.50 * specificity), 3)

    evidence = [f"title:{evidence_by_family[best]}"] if best in evidence_by_family else []
    evidence.extend(f"skill:{skill}" for skill in skills[:4])
    return Classification(best, confidence, skills, seniority, evidence[:8])


def pattern_integrity_errors() -> list[str]:
    """Return suspicious non-ASCII regex patterns instead of hiding the defect."""
    errors: list[str] = []
    for label, mapping in (("skill", SKILL_PATTERNS), ("family", ROLE_FAMILIES)):
        for name, pattern in mapping.items():
            bad = [repr(c) for c in pattern if ord(c) > 127]
            if bad:
                errors.append(f"{label}:{name} contains non-ASCII regex characters {bad}")
    return errors
