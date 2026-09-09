from qa.engine import GroundedQAEngine
from crawler.fetcher import CrawledPage

def test_grounded_qa_verbatim_verification():
    html_content = "<html><body><p>Our official business hours are Monday to Friday, 9:00 AM to 6:00 PM PST.</p></body></html>"
    page = CrawledPage(
        original_url="https://example.com/contact",
        final_url="https://example.com/contact",
        status_code=200,
        depth=0,
        headers={"content-type": "text/html"},
        content=html_content.encode("utf-8"),
        text=html_content
    )
    crawl_data = {"crawled_pages": {"https://example.com/contact": page}}
    
    engine = GroundedQAEngine(crawl_data, score_threshold=0.1)
    res = engine.answer_query("What are your business hours?")
    
    assert res["url"] == "https://example.com/contact"
    assert "Monday to Friday" in res["excerpt"]
    
    # Test unanswerable query returns null
    res_null = engine.answer_query("What is your refund policy for space rockets?")
    assert res_null["url"] is None
    assert res_null["excerpt"] is None
