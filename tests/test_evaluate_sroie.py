"""Tests for the SROIE real-receipt evaluation and the DATE_ORDER setting."""

from datetime import date

from src import clean, config, evaluate_sroie

LABEL = {"company": "BOOK TA .K (TAMAN DAYA) SDN BHD", "date": "25/12/2018",
         "address": "NO.53, JALAN SAGU 18, 81100 JOHOR BAHRU", "total": "9.00"}

GOOD_TEXT = """BOOK TA .K (TAMAN DAYA) SDN BHD
NO.53 55,57 & 59, JALAN SAGU 18
DATE: 25/12/2018
SUBTOTAL 9.00
TOTAL 9.00"""


def test_label_dates_are_day_first():
    assert evaluate_sroie.parse_label_date("25/12/2018") == date(2018, 12, 25)
    assert evaluate_sroie.parse_label_date("15-01-2019") == date(2019, 1, 15)
    assert evaluate_sroie.parse_label_date("rubbish") is None


def test_normalize_name():
    assert evaluate_sroie.normalize_name("Book Ta .K (Taman  Daya) Sdn Bhd") == "BOOK TA K TAMAN DAYA SDN BHD"


def test_score_receipt_all_right(monkeypatch):
    monkeypatch.setattr(config, "DATE_ORDER", "DMY")
    result = evaluate_sroie.score_receipt(GOOD_TEXT, LABEL)
    assert result["total"] and result["date"] and result["vendor_exact"] and result["vendor_close"]


def test_score_receipt_wrong_total(monkeypatch):
    monkeypatch.setattr(config, "DATE_ORDER", "DMY")
    result = evaluate_sroie.score_receipt(GOOD_TEXT.replace("TOTAL 9.00", "TOTAL 9.50"), LABEL)
    assert result["total"] is False


def test_date_order_setting(monkeypatch):
    monkeypatch.setattr(config, "DATE_ORDER", "MDY")
    assert clean.clean_date("06/07/2026") == date(2026, 6, 7)
    monkeypatch.setattr(config, "DATE_ORDER", "DMY")
    assert clean.clean_date("06/07/2026") == date(2026, 7, 6)
    assert clean.clean_date("25/12/2018") == date(2018, 12, 25)


def test_splits_do_not_overlap():
    assert set(evaluate_sroie.DEV_IDS).isdisjoint(set(evaluate_sroie.TEST_IDS))
    assert len(evaluate_sroie.DEV_IDS) + len(evaluate_sroie.TEST_IDS) == 626
