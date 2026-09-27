from hiringleads.sanitize import sanitize_raw


def test_sanitize_raw_removes_contact_and_applicant_keys():
    value = sanitize_raw({
        "id": "123",
        "title": "Engineer",
        "email": "candidate@example.com",
        "applicant": {"name": "Person"},
        "nested": {"phone": "123"},
    })
    assert "email" not in value
    assert "applicant" not in value
    assert "nested" not in value
    assert value["title"] == "Engineer"
