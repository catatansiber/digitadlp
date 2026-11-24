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
