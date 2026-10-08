"""Regression checks for preserved screens against main's updated backend."""
from datetime import datetime, timezone
from sqlmodel import SQLModel, Session, create_engine


def test_preserved_and_new_investigation_routes_are_available():
    from app.routers.investigate import router
    routes = {(method, route.path) for route in router.routes for method in route.methods}
    assert {
        ("POST", "/investigate/url"), ("GET", "/investigate/comments/{post_id}"),
        ("POST", "/investigate/comments"), ("GET", "/investigate/sleuth"),
        ("GET", "/investigate/username"), ("POST", "/investigate/explain"),
        ("POST", "/investigate/reverse-image"),
    } <= routes


def test_old_dashboard_measurements_and_new_kpis_agree(monkeypatch):
    from app.models import Alert, Post
    from app.routers import stats
    monkeypatch.setattr(stats, "platform_status", lambda: [])
    monkeypatch.setattr(stats, "campaign_count", lambda: 2)
    monkeypatch.setattr(stats, "detect_emerging", lambda **kwargs: {"total": 1, "count": 1})
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        session.add(Post(id="negative", content_hash="negative", platform="X", author_handle="citizen", text="Concerning post", sentiment_label="negative", concern_score=75, created_at=now))
        session.add(Post(id="neutral", content_hash="neutral", platform="X", author_handle="desk", text="Routine bulletin", sentiment_label="neutral", concern_score=10, created_at=now))
        session.add(Alert(id="critical", post_id="negative", severity="critical", status="new", title="Review", created_at=now))
        session.commit()
        kpis = stats.get_stats(session)["kpis"]
    assert kpis["active_threats"] == 1
    assert kpis["critical_alerts"] == kpis["critical_alerts_open"] == 1
    assert kpis["campaigns"] == kpis["fake_pr_campaigns"] == 2
    assert kpis["alert_posts"] == 1
    engine.dispose()
