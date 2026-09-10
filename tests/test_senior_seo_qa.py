import os
import pytest
from crawler.fetcher import CrawledPage
from qa.engine import GroundedQAEngine
from utils.llm_helper import llm_helper


@pytest.fixture
def mock_seo_audit_data():
    html_home = """
    <html>
      <head>
        <title>FastCloud Hosting - Ultra-fast Managed Cloud Servers</title>
        <meta name="description" content="Deploy lightning-fast cloud servers with 99.99% uptime guarantee and enterprise DDoS protection.">
      </head>
      <body>
        <h1>Managed Cloud Infrastructure for Developers</h1>
        <p>FastCloud provides automated Kubernetes clusters, managed PostgreSQL databases, and edge CDN storage.</p>
        <a href="https://fastcloud.io/non-existent-page">Broken Documentation Link</a>
      </body>
    </html>
    """
    html_contact = """
    <html>
      <head>
        <title>Contact FastCloud Sales and Enterprise Support</title>
        <meta name="description" content="Reach our 24/7 technical support team and global sales representatives via phone or email.">
      </head>
      <body>
        <h1>Get in Touch with FastCloud</h1>
        <p>For sales inquiries, call our main hotline at +1-800-555-0144 or visit our San Francisco office at 500 Howard Street, Suite 400, San Francisco, CA 94105.</p>
      </body>
    </html>
    """

    page_home = CrawledPage(
        original_url="https://fastcloud.io/",
        final_url="https://fastcloud.io/",
        status_code=200,
        depth=0,
        headers={"content-type": "text/html"},
        content=html_home.encode("utf-8"),
        text=html_home,
    )
    page_contact = CrawledPage(
        original_url="https://fastcloud.io/contact",
        final_url="https://fastcloud.io/contact",
        status_code=200,
        depth=1,
        headers={"content-type": "text/html"},
        content=html_contact.encode("utf-8"),
        text=html_contact,
    )

    audit_findings = [
        {
            "metric": "broken_internal_link",
            "severity": "high",
            "page": ["https://fastcloud.io/"],
            "evidence": "Internal link pointing to non-existent page 'https://fastcloud.io/non-existent-page' (404/Error).",
            "suggested_fix": "Update or remove the broken href attribute to point to a valid target URL."
        },
        {
            "metric": "missing_canonical_tag",
            "severity": "low",
            "page": "https://fastcloud.io/contact",
            "evidence": "No <link rel=\"canonical\"> tag found in head.",
            "suggested_fix": "Add a self-referencing canonical URL tag to prevent duplicate content indexing."
        }
    ]

    nap_report = [
        {
            "field": "phone",
            "verdict": "consistent",
            "confidence": "high",
            "values": ["+1-800-555-0144"],
            "normalized_values": ["+18005550144"]
        },
        {
            "field": "address",
            "verdict": "consistent",
            "confidence": "high",
            "values": ["500 Howard Street, Suite 400, San Francisco, CA 94105"],
            "normalized_values": ["500 howard st ste 400 san francisco ca 94105"]
        }
    ]

    return {
        "url": "https://fastcloud.io/",
        "crawled_pages": {
            "https://fastcloud.io/": page_home,
            "https://fastcloud.io/contact": page_contact,
        },
        "audit": audit_findings,
        "nap_report": nap_report,
        "crawl_stats": {"crawled": 2, "skipped": 0},
    }


def test_groq_models_dynamic_resolution():
    """Ensure llm_helper auto-detects active models without 404 Model Not Found errors."""
    assert llm_helper.has_key() is True
    assert llm_helper.quick_model != ""
    assert llm_helper.deep_model != ""
    # Neither should be the discontinued model names that caused 404
    assert llm_helper.quick_model != "llama-3.1-8b-instant"
    assert llm_helper.deep_model != "llama-3.3-70b-versatile"


def test_seo_audit_queries_retrieval(mock_seo_audit_data):
    """Verify that asking about SEO issues retrieves the audit findings."""
    engine = GroundedQAEngine(mock_seo_audit_data)
    
    passages = engine.get_passages("What broken links or high severity SEO issues did the audit find?", top_n=3)
    assert len(passages) > 0
    # Should retrieve the broken_internal_link audit finding
    matched = [p for p in passages if "broken" in p["excerpt"].lower()]
    assert len(matched) > 0
    assert matched[0]["metric"] == "broken_internal_link"


def test_nap_queries_retrieval(mock_seo_audit_data):
    """Verify that asking about NAP or phone numbers retrieves NAP consistency."""
    engine = GroundedQAEngine(mock_seo_audit_data)
    
    passages = engine.get_passages("What is the phone number and NAP consistency for this business?", top_n=3)
    assert len(passages) > 0
    matched = [p for p in passages if "+1-800-555-0144" in p["excerpt"] or "+18005550144" in p["excerpt"]]
    assert len(matched) > 0


def test_website_content_retrieval(mock_seo_audit_data):
    """Verify that asking about services or features retrieves crawled page content."""
    engine = GroundedQAEngine(mock_seo_audit_data)
    
    passages = engine.get_passages("What database and infrastructure services does FastCloud offer?", top_n=3)
    assert len(passages) > 0
    assert any("Kubernetes" in p["excerpt"] or "PostgreSQL" in p["excerpt"] for p in passages)


def test_senior_seo_grounded_answer(mock_seo_audit_data):
    """Verify synthesis produces a Senior SEO Auditor response grounded in the audit data."""
    engine = GroundedQAEngine(mock_seo_audit_data)
    
    ans = engine.answer_query("Give me a technical breakdown of the broken link issue on this site.", deep=False)
    assert ans["synthesized"] is True
    assert ans["answer"] is not None
    assert len(ans["sources"]) > 0
    # The senior SEO dev should mention the broken link or 404 or fix
    answer_text = ans["answer"].lower()
    assert any(term in answer_text for term in ["broken", "link", "404", "href", "internal"])


def test_conversational_followup_expansion(mock_seo_audit_data):
    """Verify conversational follow-ups like 'tell me more about it?' expand using chat history."""
    engine = GroundedQAEngine(mock_seo_audit_data)
    history = [
        {"role": "user", "content": "What database solutions are available?"},
        {"role": "assistant", "content": "FastCloud provides automated Kubernetes clusters and managed PostgreSQL databases."},
    ]
    # Follow-up query has no domain words, but history does
    passages = engine.get_passages("tell me more about it?", top_n=2, conversation_history=history)
    assert len(passages) > 0
    # Should retrieve the Kubernetes / PostgreSQL passage via history expansion
    combined_excerpts = " ".join(p["excerpt"] for p in passages)
    assert "PostgreSQL" in combined_excerpts or "Kubernetes" in combined_excerpts
