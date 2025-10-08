from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database
from app.database import Base, get_db_session
from app.main import create_app

# Ensure models are imported so metadata is populated before creating tables.
import app.models  # noqa: F401


def create_test_client() -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    database._engine = engine  # type: ignore[attr-defined]
    database._SessionLocal = session_factory  # type: ignore[attr-defined]
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db
    return TestClient(app)


def sample_payload() -> list[dict]:
    published = datetime(2024, 6, 1, tzinfo=timezone.utc).isoformat()
    fetched = datetime(2024, 6, 2, tzinfo=timezone.utc).isoformat()
    return [
        {
            "source": {
                "source_slug": "aliyun_security",
                "external_id": "12345",
                "origin_url": "https://www.aliyun.com/notice/12345",
            },
            "content": {
                "title": "Test bulletin",
                "summary": "Summary",
                "body_text": "Body",
                "published_at": published,
                "language": "zh",
            },
            "severity": "medium",
            "fetched_at": fetched,
            "labels": ["security"],
            "topics": ["official_bulletin"],
            "extra": {"origin_region": "cn"},
            "raw": {"sample": True},
        }
    ]


def test_ingest_endpoint_creates_and_deduplicates_records():
    client = create_test_client()
    payload = sample_payload()

    response = client.post("/v1/ingest/bulletins", json=payload)
    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "duplicates": 0}

    response_dup = client.post("/v1/ingest/bulletins", json=payload)
    assert response_dup.status_code == 202
    assert response_dup.json() == {"accepted": 0, "duplicates": 1}


def test_bulletin_list_and_detail_endpoints():
    client = create_test_client()
    payload = sample_payload()
    post_resp = client.post("/v1/ingest/bulletins", json=payload)
    assert post_resp.status_code == 202

    list_resp = client.get("/v1/bulletins")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["pagination"] == {"total": 1, "limit": 20, "offset": 0}
    assert len(body["items"]) == 1
    bulletin_id = body["items"][0]["id"]
    assert body["items"][0]["source_slug"] == "aliyun_security"
    assert body["items"][0]["extra"]["origin_region"] == "cn"

    detail_resp = client.get(f"/v1/bulletins/{bulletin_id}")
    assert detail_resp.status_code == 200
    detail_json = detail_resp.json()
    assert detail_json["id"] == bulletin_id
    assert detail_json["title"] == "Test bulletin"
    assert detail_json["extra"]["origin_region"] == "cn"

    not_found = client.get("/v1/bulletins/9999")
    assert not_found.status_code == 404


def test_rss_feed_and_frontend_rendering():
    client = create_test_client()
    payload = sample_payload()
    post_resp = client.post("/v1/ingest/bulletins", json=payload)
    assert post_resp.status_code == 202

    rss_resp = client.get("/v1/bulletins/rss")
    assert rss_resp.status_code == 200
    assert rss_resp.headers["content-type"].startswith("application/rss+xml")
    assert b"<rss" in rss_resp.content

    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "SecLens 情报雷达" in homepage.text
    assert "最新采集的全量资讯流" in homepage.text
    assert "Test bulletin" in homepage.text

    home_api = client.get("/v1/bulletins/home")
    assert home_api.status_code == 200
    home_payload = home_api.json()
    assert isinstance(home_payload, list)
    assert len(home_payload) >= 1
