import os
import json
import argparse
import sys
from typing import Optional, List, Dict
from crawler.fetcher import Crawler
from seo.auditor import SEOAuditor
from nap.checker import NAPChecker
from qa.engine import GroundedQAEngine


def run_agent(
    url: str,
    query: Optional[str] = None,
    output_dir: str = "outputs",
    conversation_history: Optional[List[Dict]] = None,
) -> dict:
    # On Vercel (and other serverless platforms) only /tmp is writable
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        output_dir = "/tmp/outputs"

    os.makedirs(output_dir, exist_ok=True)

    print(f"[1/4] Crawling domain starting at: {url}")
    crawler   = Crawler(start_url=url)
    crawl_data = crawler.crawl()
    pages_crawled  = len(crawl_data["crawled_pages"])
    pages_skipped  = len(crawl_data["skipped_pages"])
    print(f"      Crawled {pages_crawled} page(s). Skipped {pages_skipped} page(s).")

    print("[2/4] Running On-Page SEO Auditor...")
    auditor       = SEOAuditor(crawl_data)
    audit_results = auditor.audit()
    audit_file    = os.path.join(output_dir, "audit.json")
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2)
    print(f"      Generated {len(audit_results)} finding(s) -> {audit_file}")

    print("[3/4] Running NAP Consistency Checker...")
    nap_checker  = NAPChecker(crawl_data)
    nap_results  = nap_checker.check()
    nap_file     = os.path.join(output_dir, "nap_report.json")
    with open(nap_file, "w", encoding="utf-8") as f:
        json.dump(nap_results, f, indent=2)
    print(f"      Generated NAP consistency report -> {nap_file}")

    print("[4/4] Running Grounded Website Q&A...")
    qa_engine     = GroundedQAEngine(crawl_data)
    answer_result = qa_engine.answer_query(query, conversation_history or [])
    answer_file   = os.path.join(output_dir, "answer.json")
    with open(answer_file, "w", encoding="utf-8") as f:
        json.dump(answer_result, f, indent=2)
    status = "Synthesized answer" if answer_result.get("synthesized") else \
             ("Found excerpt" if answer_result.get("excerpt") else "Null (no match)")
    print(f"      Answer status: {status} -> {answer_file}")

    print("\n[COMPLETE] All outputs generated successfully.")

    return {
        "audit":        audit_results,
        "nap_report":   nap_results,
        "answer":       answer_result,
        "crawl_stats":  {"crawled": pages_crawled, "skipped": pages_skipped},
        # Return crawl_data so server can cache it for follow-up /api/chat calls
        "_crawl_data":  crawl_data,
    }


def main():
    parser = argparse.ArgumentParser(description="Auditgo SEO Audit Agent CLI")
    parser.add_argument("--url",        required=True,  help="Target website URL to audit")
    parser.add_argument("--query",      required=False, default=None, help="Optional Q&A question")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    args = parser.parse_args()
    try:
        result = run_agent(url=args.url, query=args.query, output_dir=args.output_dir)
        # Strip internal crawl_data from CLI output
        result.pop("_crawl_data", None)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
