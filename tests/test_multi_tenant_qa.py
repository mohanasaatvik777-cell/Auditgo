import os
import pytest
from fastapi.testclient import TestClient
from server import app, session_manager, _cache_key
from qa.engine import GroundedQAEngine
from utils.llm_helper import llm_helper
from crawler.fetcher import CrawledPage


@pytest.fixture
def dummy_crawl_data():
    html_1 = "<html><head><title>Example Website</title></head><body><h1>Welcome to Example Corp</h1><p>We provide enterprise cloud solutions and SEO analytics tools.</p></body></html>"
    html_2 = "<html><head><title>About Us</title></head><body><h1>About Example Corp</h1><p>Contact our support team at support@example.com or call +1-800-555-0199.</p></body></html>"
    page1 = CrawledPage(
        original_url="https://example.com/",
        final_url="https://example.com/",
        status_code=200,
        depth=0,
        headers={"content-type": "text/html"},
        content=html_1.encode("utf-8"),
        text=html_1,
    )
    page2 = CrawledPage(
        original_url="https://example.com/about",
        final_url="https://example.com/about",
        status_code=200,
        depth=1,
        headers={"content-type": "text/html"},
        content=html_2.encode("utf-8"),
        text=html_2,
    )
    return {
        "crawled_pages": {
            "https://example.com/": page1,
            "https://example.com/about": page2,
        }
    }


def test_groq_env_key_usage():
    """Verify LLM helper automatically detects and uses backend .env GROQ_API_KEY."""
    assert llm_helper.has_key() is True
    assert llm_helper.api_key != ""


def test_qa_engine_overview_fallback(dummy_crawl_data):
    """Verify GroundedQAEngine returns website context for broad/overview queries."""
    engine = GroundedQAEngine(dummy_crawl_data)
    
    # Specific query
    specific = engine.get_passages("enterprise cloud solutions", top_n=2)
    assert len(specific) > 0
    assert "enterprise cloud solutions" in specific[0]["excerpt"]

    # Broad/overview query where BM25 exact match might be 0
    overview = engine.get_passages("What is this website about?", top_n=2, allow_fallback=True)
    assert len(overview) > 0
    assert overview[0]["url"] in ["https://example.com/", "https://example.com/about"]


def test_multi_tenant_session_isolation(dummy_crawl_data):
    """Verify user sessions maintain separate crawl data and chat histories without mixing up."""
    session_a = session_manager.get_session("user_session_A")
    session_b = session_manager.get_session("user_session_B")

    url_key = _cache_key("https://example.com")
    
    # Session A stores crawl and chat
    session_a.crawls[url_key] = dummy_crawl_data
    session_a.chat_histories[url_key] = [
        {"role": "user", "content": "What is session A's question?"},
        {"role": "assistant", "content": "Session A answer."},
    ]

    # Session B stores different chat
    session_b.crawls[url_key] = dummy_crawl_data
    session_b.chat_histories[url_key] = [
        {"role": "user", "content": "What is session B's question?"},
        {"role": "assistant", "content": "Session B answer."},
    ]

    # Assert isolation
    assert session_a.chat_histories[url_key][0]["content"] == "What is session A's question?"
    assert session_b.chat_histories[url_key][0]["content"] == "What is session B's question?"
    assert session_a.session_id != session_b.session_id


def test_server_session_endpoints(dummy_crawl_data):
    """Test API endpoints for session health, history, and clear."""
    client = TestClient(app)

    # 1. Health check
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["groq_key"] is True

    # 2. Seed session data manually in server manager
    url = "https://test-site.org"
    url_key = _cache_key(url)
    session_id_1 = "tenant_user_1"
    session_id_2 = "tenant_user_2"

    s1 = session_manager.get_session(session_id_1)
    s2 = session_manager.get_session(session_id_2)

    s1.chat_histories[url_key] = [{"role": "user", "content": "User 1 query"}]
    s2.chat_histories[url_key] = [{"role": "user", "content": "User 2 query"}]

    # 3. Get history for User 1
    h1_res = client.get(f"/api/chat/history?url={url}", headers={"X-Session-ID": session_id_1})
    assert h1_res.status_code == 200
    assert h1_res.json()["history"][0]["content"] == "User 1 query"

    # 4. Get history for User 2
    h2_res = client.get(f"/api/chat/history?url={url}", headers={"X-Session-ID": session_id_2})
    assert h2_res.status_code == 200
    assert h2_res.json()["history"][0]["content"] == "User 2 query"

    # 5. Clear User 1 history
    clear_res = client.post("/api/chat/clear", json={"url": url}, headers={"X-Session-ID": session_id_1})
    assert clear_res.status_code == 200

    # User 1 history cleared
    h1_after = client.get(f"/api/chat/history?url={url}", headers={"X-Session-ID": session_id_1})
    assert h1_after.json()["history"] == []

    # User 2 history remains intact
    h2_after = client.get(f"/api/chat/history?url={url}", headers={"X-Session-ID": session_id_2})
    assert len(h2_after.json()["history"]) == 1
