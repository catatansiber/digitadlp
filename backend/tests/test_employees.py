import pytest
from openpyxl import Workbook

from digitadlp.detect.employees import EmployeeDirectory


def test_directory_strips_titles():
    d = EmployeeDirectory.from_names(["Bambang Sutrisno"])
    assert d.is_employee("Drs. Bambang Sutrisno, M.Si") is True
    assert d.is_employee("Siti Rahmawati") is False


@pytest.mark.parametrize(
    "name",
    [
        "Ir. H. Bambang Sutrisno, S.T., M.T.",
        "dr. Bambang Sutrisno",
        "Bambang   Sutrisno S.Kom",
        "Hj. Bambang Sutrisno, S.E., M.M.",
        "BAMBANG SUTRISNO, S.Pd",
        "Bambang Sutrisno, S.H.",
    ],
)
def test_title_variants(name):
    assert EmployeeDirectory.from_names(["Bambang Sutrisno"]).is_employee(name)


def test_titles_stripped_from_directory_side():
    d = EmployeeDirectory.from_names(["Drs. Bambang Sutrisno, M.Si"])
    assert d.is_employee("Bambang Sutrisno")


def test_empty_name_not_employee():
    assert EmployeeDirectory.from_names(["Dr."]).is_employee("Ir.") is False


def test_from_xlsx(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["No", "NIP", "Nama"])
    ws.append([1, "198001012005011001", "Drs. Bambang Sutrisno, M.Si"])
    ws.append([2, "199001012015012002", "Siti Aminah"])
    p = tmp_path / "pegawai.xlsx"
    wb.save(p)
    d = EmployeeDirectory.from_xlsx(p)
    assert d.is_employee("bambang sutrisno")
    assert d.is_employee("Siti Aminah, S.Kom")
    assert not d.is_employee("Siti Rahmawati")


def test_nip_from_xlsx(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["NAMA", "Nip"])
    ws.append(["Siti Aminah", "1990 0101 2015 01 2002"])
    ws.append(["Budi", None])
    p = tmp_path / "p.xlsx"
    wb.save(p)
    d = EmployeeDirectory.from_xlsx(p)
    assert d.is_employee_nip("199001012015012002")
    assert d.is_employee_nip("19900101 201501 2002")
    assert not d.is_employee_nip("199001012015012003")
    assert not d.is_employee_nip("")
    assert not d.is_employee_nip("abc")


def test_middle_initial_kept():
    d = EmployeeDirectory.from_names(["Siti H Rahmawati"])
    assert d.is_employee("Hj. Siti H Rahmawati")
    assert not d.is_employee("Siti Rahmawati")


@pytest.mark.parametrize(
    "name",
    [
        "Bambang Sutrisno SH",
        "Bambang Sutrisno, ST, MT",
        "Bambang Sutrisno SE",
        "Bambang Sutrisno, S. Kom",
        "Bambang Sutrisno, S.Pd.I",
        "Bambang Sutrisno, M.Pd.I",
        "Bambang Sutrisno, S.Pd.I., M.Pd.I.",
    ],
)
def test_more_trailing_titles(name):
    assert EmployeeDirectory.from_names(["Bambang Sutrisno"]).is_employee(name)
