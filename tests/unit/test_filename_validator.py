"""M2 Task 3: Filename validation tests — full-name-with-extension contract."""
import pytest
from src.core.filename_validator import validate_filename

def test_valid_names():
    assert validate_filename("report.pdf", ".pdf").is_valid
    assert validate_filename("2025-Report.pdf", ".pdf").is_valid
    assert validate_filename("file_name_v2.txt", ".txt").is_valid
    assert validate_filename("a", "").is_valid

def test_empty_rejected():
    r = validate_filename("", ".pdf"); assert not r.is_valid

def test_illegal_chars():
    for c in '<>:"/\\|?*':
        r = validate_filename(f"test{c}name.pdf", ".pdf")
        assert not r.is_valid

def test_trailing_space():
    r = validate_filename("name .pdf", ".pdf"); assert not r.is_valid

def test_trailing_dot():
    r = validate_filename("name..pdf", ".pdf"); assert not r.is_valid

def test_reserved_con(): assert not validate_filename("CON", "").is_valid
def test_reserved_con_ext(): assert not validate_filename("CON.txt", ".txt").is_valid
def test_reserved_case(): assert not validate_filename("con.txt", ".txt").is_valid

def test_ext_replacement(): r=validate_filename("foo.exe",".pdf"); assert not r.is_valid
def test_ext_removed(): r=validate_filename("foo",".pdf"); assert not r.is_valid
def test_double_ext_attack(): r=validate_filename("foo.pdf.exe",".pdf"); assert not r.is_valid
def test_ext_protected(): assert validate_filename("newname.pdf", ".pdf").is_valid
def test_too_long(): r=validate_filename("a"*256+".pdf",".pdf"); assert not r.is_valid
