"""Report selection and exports use the same configured concern bands."""
import importlib.util
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.models import Post, Report

if os.environ.get("REPORT_SERVICE_PATH"):
    spec = importlib.util.spec_from_file_location("staged_report_service", os.environ["REPORT_SERVICE_PATH"])
    reports = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reports)
else:
    from app.services import report_service as reports


def post(identifier, score, sentiment="negative", **kwargs):
    return Post(id=identifier, content_hash=identifier, platform="X", author_handle=identifier,
                text="Review this post <carefully> & compare the context.", language="English",
                concern_score=score, sentiment_label=sentiment, **kwargs)


@pytest.fixture(autouse=True)
def thresholds(monkeypatch):
    monkeypatch.setattr(reports.settings, "ELEVATED_THRESHOLD", 35)
    monkeypatch.setattr(reports.settings, "ALERT_THRESHOLD", 50)
    monkeypatch.setattr(reports.settings, "CRITICAL_THRESHOLD", 60)


def test_medium_follow_up_is_separate_limited_and_has_reasons():
    posts = [post("high", 65), post("positive", 45, "positive"), post("routine", 34),
             post("medium-1", 49), post("medium-2", 40, is_amplified=True),
             post("medium-3", 38, engagement={"shares": 12}),
             post("medium-4", 36, keywords=["concerning phrase"])]
    urgent, medium = reports._select_report_posts(posts)
    assert [item["id"] for item in urgent] == ["high"]
    assert len(medium) == 3
    assert {item["id"] for item in medium} == {"medium-2", "medium-3", "medium-4"}
    assert all(item["concern_level"] == "medium" and item["review_reasons"] for item in medium)
    assert not {item["id"] for item in urgent} & {item["id"] for item in medium}


def test_selection_respects_configured_thresholds(monkeypatch):
    monkeypatch.setattr(reports.settings, "ELEVATED_THRESHOLD", 50)
    monkeypatch.setattr(reports.settings, "ALERT_THRESHOLD", 65)
    monkeypatch.setattr(reports.settings, "CRITICAL_THRESHOLD", 74)
    urgent, medium = reports._select_report_posts([post("below", 49), post("floor", 50), post("ceiling", 64), post("high", 65)])
    assert [item["id"] for item in urgent] == ["high"]
    assert {item["id"] for item in medium} == {"floor", "ceiling"}


def test_no_medium_posts_means_no_invented_follow_up():
    urgent, medium = reports._select_report_posts([post("high", 61), post("neutral", 41, "neutral")])
    assert len(urgent) == 1
    assert medium == []


@pytest.mark.parametrize("hours,label", [(6, "6 hours"), (24, "24 hours"), (72, "72 hours"), (168, "7 days")])
def test_payload_and_exports_include_follow_up(monkeypatch, tmp_path, hours, label):
    posts = [post("urgent", 65), post("watch", 44, engagement={"shares": 8})]
    results = iter([posts, []])
    @contextmanager
    def session():
        yield SimpleNamespace(exec=lambda query: SimpleNamespace(all=lambda: next(results)))
    monkeypatch.setattr(reports, "session_scope", session)
    monkeypatch.setitem(sys.modules, "app.services.network_service", SimpleNamespace(get_network=lambda hours: {"clusters": []}))
    monkeypatch.setitem(sys.modules, "app.services.trend_service", SimpleNamespace(get_trends=lambda hours: {"hashtags": [], "regions": []}))
    monkeypatch.setattr(reports.settings, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(reports, "FONT_DIR", Path(__file__).resolve().parents[1] / "app/assets/fonts")
    payload = reports._build_payload(hours)
    assert f"past {label}" in payload["summary"]
    assert "168h" not in payload["summary"]
    assert len(payload["summary_points"]) == 4
    assert payload["concern_thresholds"]["medium"] == 35
    assert [item["id"] for item in payload["follow_up_posts"]] == ["watch"]
    report = Report(id="selection-test", title="Readable incident report", kind="incident", period_hours=hours, payload=payload)
    pdf = reports._render_pdf(report)
    assert Path(pdf).read_bytes().startswith(b"%PDF")
    excel = reports._render_xlsx(report)
    workbook = load_workbook(excel)
    summary = {row[0]: row[1] for row in workbook["Summary"].values if row[0]}
    assert summary["Report Period"] == f"Past {label}"
    sheet = workbook["Medium Concerns"]
    assert sheet["C2"].value == "watch"
    assert "Shared 8 times" in sheet["F2"].value
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:H2"
    workbook.close()


def test_report_time_is_in_12_hour_ist():
    assert reports._report_time("2026-10-08T09:00:00Z") == "08 Oct 2026, 02:30 PM IST"


@pytest.mark.parametrize("hours,label", [(1, "1 hour"), (6, "6 hours"), (24, "24 hours"), (72, "72 hours"), (168, "7 days")])
def test_report_period_matches_filter(hours, label):
    assert reports._report_period(hours) == label
