from hiringleads.classify import classify, pattern_integrity_errors, extract_skills


def test_backend_classification_uses_ascii_swe_pattern():
    result = classify("Senior SWE")
    assert result.role_family == "backend"
    assert result.confidence > 0


def test_generic_ml_signal_is_classified():
    result = classify("Machine Learning Engineer", "Python, PyTorch, model serving")
    assert result.role_family == "ml"
    assert "python" in result.skills
    assert "pytorch" in result.skills


def test_non_engineering_title_is_rejected():
    result = classify("Sales Engineer")
    assert result.rejected is True
    assert result.role_family is None


def test_classifier_explains_match():
    result = classify("React Frontend Engineer")
    assert result.evidence
    assert result.evidence[0].startswith("title:")


def test_taxonomy_has_no_non_ascii_regex_tokens():
    assert pattern_integrity_errors() == []


def test_single_skill_in_title_is_retained():
    assert "rust" in extract_skills("Rust Engineer", None)
