from digitadlp.models import Finding, Kind, Strength


def test_strength_mapping():
    assert Finding(Kind.NIK, 0, 16, "6474015203880002", "regex").strength == Strength.STRONG
    assert Finding(Kind.NAME_EMPLOYEE, 0, 3, "Budi", "ner").strength == Strength.EMPLOYEE
    assert Finding(Kind.PHONE, 0, 12, "081234567890", "regex").strength == Strength.MEDIUM
