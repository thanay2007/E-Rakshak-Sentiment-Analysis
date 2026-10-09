"""Persistence, labeling and access control for the manual demo directory."""
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from app.data.directory_seed import seed_demo_directory
from app.database import get_session
from app.models.demo_directory import DEMO_LABEL, DemoDirectoryProfile
from app.routers.demo_directory import router
from app.security.deps import password_not_expired


@pytest.fixture
def directory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    DemoDirectoryProfile.__table__.create(engine)
    with Session(engine) as session:
        assert seed_demo_directory(session) == 3
    app = FastAPI()
    app.include_router(router, prefix="/api", dependencies=[Depends(password_not_expired)])

    def session_dependency():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    with TestClient(app) as client:
        yield client, app, engine
    engine.dispose()


def test_seed_is_idempotent_and_persists_portraits(directory):
    _, _, engine = directory
    with Session(engine) as session:
        assert seed_demo_directory(session) == 0
        rows = session.exec(select(DemoDirectoryProfile)).all()
        assert len(rows) == 3
        for row in rows:
            assert row.image_png.startswith(b"\x89PNG\r\n\x1a\n")
            assert row.case_history
            assert all(case["is_fictional"] for case in row.case_history)


def test_directory_and_portraits_require_login(directory):
    client, _, _ = directory
    for path in ("/api/demo-directory", "/api/demo-directory/demo-milo-muffin",
                 "/api/demo-directory/demo-milo-muffin/image"):
        assert client.get(path).status_code == 401


def test_manual_search_detail_and_image(directory):
    client, app, _ = directory
    app.dependency_overrides[password_not_expired] = lambda: None
    response = client.get("/api/demo-directory", params={"q": "MILO"})
    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["selection_method"] == "manual"
    assert profile["demo_label"] == DEMO_LABEL
    assert all(case["demo_label"] == DEMO_LABEL for case in profile["case_history"])
    assert client.get(f"/api/demo-directory/{profile['id']}").json() == profile
    image = client.get(profile["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-demo-data"] == "synthetic"
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert client.get("/api/demo-directory", params={"q": "%"}).json()["profiles"] == []


def test_unknown_record_returns_404(directory):
    client, app, _ = directory
    app.dependency_overrides[password_not_expired] = lambda: None
    for suffix in ("", "/image"):
        assert client.get(f"/api/demo-directory/unknown{suffix}").status_code == 404
