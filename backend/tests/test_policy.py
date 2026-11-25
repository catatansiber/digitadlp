import pytest

from digitadlp.models import Action, Finding, Kind, Label, Version
from digitadlp.policy import action_for, mask_value, placeholder, suggest_label


def F(kind, text):
    return Finding(kind, 0, len(text), text, "test")


nik = F(Kind.NIK, "6474011203900002")
emp = F(Kind.NAME_EMPLOYEE, "Budi Santoso")
phone = F(Kind.PHONE, "081234567890")
nip = F(Kind.NIP, "198503122010011002")


def test_label_rules():
    assert suggest_label([]) == Label.PUBLIK
    assert suggest_label([emp]) == Label.INTERNAL
    assert suggest_label([nip]) == Label.INTERNAL
    assert suggest_label([emp, phone]) == Label.INTERNAL
    assert suggest_label([phone]) == Label.INTERNAL
    assert suggest_label([nik]) == Label.RAHASIA
    assert suggest_label([emp, phone, nik]) == Label.RAHASIA


def test_mask_nik():
    assert mask_value(nik) == "6474********0002"


def test_mask_digits_keeps_separators():
    assert mask_value(F(Kind.NPWP, "09.254.294.3-407.000")) == "09.25*.***.*-**7.000"
    assert mask_value(F(Kind.PHONE, "0812-3456-7890")) == "0812-****-7890"


def test_mask_short_digits():
    assert mask_value(F(Kind.ACCOUNT, "12345678")) == "******78"
    assert mask_value(F(Kind.ACCOUNT, "123")) == "*23"


def test_mask_counts_digits_not_chars():
    # span extended over non-numeric neighbours
    out = mask_value(F(Kind.NIK, "NIK: 6474011203900002"))
    assert out == "NIK: 6474********0002"


def test_mask_name():
    assert mask_value(F(Kind.NAME_CITIZEN, "Siti Rahmawati")) == "Siti R*****ti"


def test_mask_name_short_words_kept():
    assert mask_value(F(Kind.NAME_CITIZEN, "Budi")) == "B***"
    assert mask_value(F(Kind.NAME_CITIZEN, "Ani")) == "A**"
    assert mask_value(F(Kind.NAME_CITIZEN, "Budi Ani")) == "B*** A**"


def test_mask_digit_kind_without_digits():
    assert mask_value(F(Kind.NIK, "bukan angka")) == "***"


def test_mask_ignores_non_ascii_digits():
    assert mask_value(F(Kind.NIK, "\u0663\u0664" + "6474011203900002")) == "\u0663\u0664" + "6474********0002"


def test_mask_birthdate():
    assert mask_value(F(Kind.BIRTHDATE, "12 Maret 1990")) == "** Maret ****"
    assert mask_value(F(Kind.BIRTHDATE, "12-03-1990")) == "**-**-****"


def test_mask_address():
    assert mask_value(F(Kind.ADDRESS, "Jl. Merdeka RT 05 RW 02")) == "Jl. Merdeka ***"
    assert mask_value(F(Kind.ADDRESS, "Jl. Melati No. 12")) == "Jl. Melati ***"
    assert mask_value(F(Kind.ADDRESS, "Jl. Mawar12 Blok A")) == "Jl. ***"
    assert mask_value(F(Kind.ADDRESS, "RT 05 RW 02")) == "***"
    assert mask_value(F(Kind.ADDRESS, "12 Jl. X")) == "***"


def test_mask_email():
    assert mask_value(F(Kind.EMAIL, "siti@example.go.id")) == "s***@example.go.id"
    assert mask_value(F(Kind.EMAIL, "@x.id")) == "***@x.id"
    assert mask_value(F(Kind.EMAIL, "bukan email")) == "b*an e*il"


SAMPLES = [
    F(Kind.NIK, "6474011203900002"),
    F(Kind.KK, "6474012005110003"),
    F(Kind.NPWP, "09.254.294.3-407.000"),
    F(Kind.ACCOUNT, "1234567890"),
    F(Kind.NIP, "198503122010011002"),
    F(Kind.PHONE, "081234567890"),
    F(Kind.EMAIL, "siti@example.go.id"),
    F(Kind.NAME_CITIZEN, "Siti Rahmawati"),
    F(Kind.NAME_EMPLOYEE, "Budi Santoso"),
    F(Kind.ADDRESS, "Jl. Merdeka No. 12 RT 05"),
    F(Kind.ADDRESS, "Jl. Merdeka Bontang"),
    F(Kind.BIRTHDATE, "12 Maret 1990"),
    F(Kind.NAME_CITIZEN, "Budi"),
    F(Kind.NAME_CITIZEN, "Ani"),
    F(Kind.NIK, "NIK: 6474011203900002 a.n."),
]


@pytest.mark.parametrize("f", SAMPLES, ids=lambda f: f"{f.kind}-{f.text}")
def test_mask_never_returns_original(f):
    assert mask_value(f) != f.text


def test_actions():
    assert action_for(nik, Version.PUBLIK) == Action.REDACT
    assert action_for(nik, Version.INTERNAL) == Action.MASK
    assert action_for(emp, Version.INTERNAL) == Action.KEEP
    assert action_for(nik, Version.RAHASIA) == Action.KEEP


def test_actions_employee():
    assert action_for(emp, Version.PUBLIK) == Action.KEEP
    assert action_for(nip, Version.PUBLIK) == Action.REDACT
    assert action_for(nip, Version.INTERNAL) == Action.KEEP
    assert action_for(phone, Version.INTERNAL) == Action.MASK
    assert action_for(phone, Version.PUBLIK) == Action.REDACT
    for f in SAMPLES + [nip]:
        assert action_for(f, Version.RAHASIA) == Action.KEEP


def test_placeholders():
    expect = {
        Kind.NIK: "[NIK]", Kind.NAME_CITIZEN: "[NAMA]", Kind.NAME_EMPLOYEE: "[NAMA]",
        Kind.ADDRESS: "[ALAMAT]", Kind.PHONE: "[HP]", Kind.EMAIL: "[EMAIL]",
        Kind.ACCOUNT: "[REKENING]", Kind.NPWP: "[NPWP]", Kind.NIP: "[NIP]",
        Kind.KK: "[KK]", Kind.BIRTHDATE: "[TGL LAHIR]",
    }
    assert set(expect) == set(Kind)
    for k, v in expect.items():
        assert placeholder(k) == v


def test_rules_override_label():
    assert suggest_label([phone], {Kind.PHONE: Label.RAHASIA}) == Label.RAHASIA
    assert suggest_label([phone], {Kind.PHONE: Label.PUBLIK}) == Label.PUBLIK
    # kind not in rules uses default
    assert suggest_label([nik, phone], {Kind.PHONE: Label.PUBLIK}) == Label.RAHASIA
    assert suggest_label([], {Kind.PHONE: Label.RAHASIA}) == Label.PUBLIK


def test_default_unchanged():
    assert suggest_label([phone], None) == suggest_label([phone])
    assert suggest_label([emp, nik]) == Label.RAHASIA
