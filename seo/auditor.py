from typing import List, Dict, Any
from bs4 import BeautifulSoup
from crawler.fetcher import CrawledPage
from utils.llm_helper import llm_helper

class SEOAuditor:
    def __init__(self, crawl_data: Dict[str, Any]):
        self.crawled_pages: Dict[str, CrawledPage] = crawl_data.get("crawled_pages", {})
        self.skipped_pages: set = crawl_data.get("skipped_pages", set())
        self.sitemap_entries: set = crawl_data.get("sitemap_entries", set())
        self.sitemap_urls: set = crawl_data.get("sitemap_urls", set())
        self.findings: List[Dict[str, Any]] = []

    def audit(self) -> List[Dict[str, Any]]:
        self.findings = []
        
        # Site-wide tracking for duplication and sitemap/hreflang checks
        title_map = {}
        fingerprint_map = {}
        has_multilang_signal = False
        broken_links_by_target = {}
        
        # First pass to check hreflang multi-language signals site-wide
        for url, page in self.crawled_pages.items():
            if page.status_code != 200 or "text/html" not in page.content_type:
                continue
            soup = BeautifulSoup(page.content, "lxml")
            if soup.find_all("link", rel=lambda r: r and "hreflang" in r.lower()):
                has_multilang_signal = True
                break

        # Iterate over all crawled pages
        for url, page in self.crawled_pages.items():
            if page.status_code >= 400 or page.status_code == 0:
                # Page itself is broken
                continue

            if "text/html" not in page.content_type:
                continue

            soup = BeautifulSoup(page.content, "lxml")

            # 1. Title Audit
            title_tag = soup.find("title")
            title_text = title_tag.get_text().strip() if title_tag else ""
            if not title_tag or not title_text:
                self._add_finding(
                    metric="missing_title",
                    page=url,
                    severity="high",
                    evidence="<head> contains no non-empty <title> element.",
                    suggested_fix="Add a unique, descriptive <title> tag between 10 and 70 characters."
                )
            else:
                if len(title_text) < 10:
                    self._add_finding(
                        metric="title_too_short",
                        page=url,
                        severity="low",
                        evidence=f"Page <title> '{title_text}' is only {len(title_text)} characters long.",
                        suggested_fix="Expand the title tag to be at least 10 characters long with relevant keywords."
                    )
                elif len(title_text) > 70:
                    self._add_finding(
                        metric="title_too_long",
                        page=url,
                        severity="low",
                        evidence=f"Page <title> '{title_text[:60]}...' is {len(title_text)} characters long.",
                        suggested_fix="Truncate title tag to under 70 characters to avoid SERP snippet clipping."
                    )

                # Duplicate title tracking
                title_map.setdefault(title_text, []).append(url)

            # 2. Meta Description Audit
            meta_desc = soup.find("meta", attrs={"name": lambda n: n and n.lower() == "description"})
            desc_text = meta_desc.get("content", "").strip() if meta_desc else ""
            if not meta_desc or not desc_text:
                self._add_finding(
                    metric="missing_meta_description",
                    page=url,
                    severity="medium",
                    evidence='No <meta name="description"> element exists in the page <head>.',
                    suggested_fix="Add a unique, descriptive meta description tag between 50 and 160 characters."
                )
            else:
                if len(desc_text) < 50:
                    self._add_finding(
                        metric="meta_description_too_short",
                        page=url,
                        severity="low",
                        evidence=f'Meta description is too short ({len(desc_text)} chars): "{desc_text}".',
                        suggested_fix="Expand meta description to at least 50 characters to effectively inform users."
                    )
                elif len(desc_text) > 160:
                    self._add_finding(
                        metric="meta_description_too_long",
                        page=url,
                        severity="low",
                        evidence=f'Meta description exceeds 160 characters ({len(desc_text)} chars).',
                        suggested_fix="Shorten meta description to 150-160 characters for optimal display in SERPs."
                    )

            # 3. H1 Tags & Heading Order Audit
            h1_tags = soup.find_all("h1")
            if len(h1_tags) == 0:
                self._add_finding(
                    metric="missing_h1",
                    page=url,
                    severity="medium",
                    evidence="No <h1> heading element found in document body.",
                    suggested_fix="Add a single <h1> heading representing the main subject of the page."
                )
            elif len(h1_tags) > 1:
                self._add_finding(
                    metric="multiple_h1",
                    page=url,
                    severity="low",
                    evidence=f"Found {len(h1_tags)} <h1> headings on the page.",
                    suggested_fix="Consolidate page headings so there is only one top-level <h1> heading."
                )

            # Heading Hierarchy Check (e.g. h3 before h2)
            headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            last_level = 0
            broken_order = False
            for h in headings:
                level = int(h.name[1])
                if last_level > 0 and level > last_level + 1:
                    broken_order = True
                    self._add_finding(
                        metric="broken_heading_order",
                        page=url,
                        severity="low",
                        evidence=f"Heading hierarchy skips levels: <h{last_level}> followed directly by <h{level}>.",
                        suggested_fix="Fix heading structure so heading levels increase sequentially without skipping."
                    )
                    break
                last_level = level

            # 4. Images Missing Alt Attributes
            imgs = soup.find_all("img")
            missing_alt_imgs = [img for img in imgs if not img.get("alt")]
            if missing_alt_imgs:
                self._add_finding(
                    metric="images_missing_alt",
                    page=url,
                    severity="low",
                    evidence=f"Found {len(missing_alt_imgs)} <img> tag(s) missing alt text.",
                    suggested_fix="Add descriptive alt attributes to all informational images for accessibility and SEO."
                )

            # 5. Internal Links to Broken Pages (404/error)
            for target_link in page.links:
                if target_link in self.crawled_pages:
                    target_page = self.crawled_pages[target_link]
                    if target_page.is_broken:
                        broken_links_by_target.setdefault(target_link, []).append(url)

            # 6. Canonical Tag Audit
            canon_link = soup.find("link", rel=lambda r: r and "canonical" in r.lower())
            if not canon_link or not canon_link.get("href"):
                self._add_finding(
                    metric="missing_canonical_tag",
                    page=url,
                    severity="low",
                    evidence="No <link rel=\"canonical\"> tag found in head.",
                    suggested_fix="Add a self-referencing canonical URL tag to prevent potential duplicate content issues."
                )

            # 7. Noindex Directives
            meta_robots = soup.find("meta", attrs={"name": lambda n: n and n.lower() == "robots"})
            robots_content = meta_robots.get("content", "").lower() if meta_robots else ""
            x_robots_tag = page.headers.get("x-robots-tag", "").lower()
            if "noindex" in robots_content or "noindex" in x_robots_tag:
                self._add_finding(
                    metric="noindex_directive_present",
                    page=url,
                    severity="medium",
                    evidence=f'Page contains noindex directive (meta: "{robots_content}", header: "{x_robots_tag}").',
                    suggested_fix="Remove noindex directive if page is intended to be indexed by search engines."
                )

            # 8. Duplicate Content Fingerprinting
            h1_text = h1_tags[0].get_text().strip() if h1_tags else ""
            fingerprint = f"{title_text.lower()}|{desc_text.lower()}|{h1_text.lower()}"
            if title_text and desc_text:
                fingerprint_map.setdefault(fingerprint, []).append(url)

            # 9. Structured Data Check (Only when page shows independent signals)
            page_text_lower = page.text.lower()
            has_commercial_signal = any(k in page_text_lower for k in ["price", "$", "contact us", "buy now", "sku", "address", "phone", "hours"])
            json_ld = soup.find_all("script", type="application/ld+json")
            itemscope = soup.find_all(attrs={"itemscope": True})
            if has_commercial_signal and not json_ld and not itemscope:
                self._add_finding(
                    metric="missing_structured_data",
                    page=url,
                    severity="low",
                    evidence="Page contains commercial/contact content but has no JSON-LD or Microdata structured data.",
                    suggested_fix="Implement Schema.org structured data (e.g. LocalBusiness, Product, Organization) to enable rich snippets."
                )

            # 10. Hreflang Check (Only if site shows multi-language signals)
            if has_multilang_signal:
                hreflangs = soup.find_all("link", rel=lambda r: r and "hreflang" in r.lower())
                if not hreflangs:
                    self._add_finding(
                        metric="missing_hreflang",
                        page=url,
                        severity="low",
                        evidence="Site uses multi-language tags, but this page is missing hreflang annotations.",
                        suggested_fix="Add appropriate rel=\"alternate\" hreflang tags for all language variations."
                    )

        # Aggregate Duplicate Titles across pages
        for title, pages in title_map.items():
            if len(pages) > 1:
                self._add_finding(
                    metric="duplicate_title",
                    page=pages,
                    severity="medium",
                    evidence=f'The title "{title}" is duplicated across {len(pages)} pages.',
                    suggested_fix="Ensure each page has a unique, specific title tag."
                )

        # Aggregate Duplicate Fingerprints
        for fp, pages in fingerprint_map.items():
            if len(pages) > 1:
                self._add_finding(
                    metric="duplicate_content_signal",
                    page=pages,
                    severity="high",
                    evidence=f"Identical Title+Meta+H1 fingerprint shared across {len(pages)} pages.",
                    suggested_fix="Differentiate page title, main H1, and meta description across distinct pages."
                )

        # Aggregate Broken Internal Links
        for target, source_pages in broken_links_by_target.items():
            self._add_finding(
                metric="broken_internal_link",
                page=source_pages,
                severity="high",
                evidence=f"Internal link pointing to non-existent page '{target}' (404/Error).",
                suggested_fix="Remove or update broken link href attribute to point to a valid URL."
            )

        # 11. Sitemap Audit Issues
        if self.sitemap_entries:
            for s_entry in self.sitemap_entries:
                if s_entry in self.crawled_pages:
                    if self.crawled_pages[s_entry].is_broken:
                        self._add_finding(
                            metric="sitemap_entry_broken",
                            page=s_entry,
                            severity="high",
                            evidence=f"URL '{s_entry}' listed in sitemap returned 404/error status.",
                            suggested_fix="Remove 404/broken URLs from sitemap.xml."
                        )

            # Crawled pages missing from sitemap
            missing_from_sitemap = [
                u for u, p in self.crawled_pages.items() 
                if p.status_code == 200 and u not in self.sitemap_entries and "text/html" in p.content_type
            ]
            if missing_from_sitemap and len(missing_from_sitemap) < len(self.crawled_pages):
                self._add_finding(
                    metric="crawled_pages_missing_from_sitemap",
                    page=missing_from_sitemap,
                    severity="low",
                    evidence=f"{len(missing_from_sitemap)} accessible HTML page(s) were crawled but omitted from sitemap.xml.",
                    suggested_fix="Include all indexable URLs in your sitemap.xml."
                )

        return self._format_output()

    def _add_finding(self, metric: str, page: Any, severity: str, evidence: str, suggested_fix: str):
        fix = llm_helper.refine_suggested_fix(metric, evidence, suggested_fix)
        item = {
            "metric": metric,
            "severity": severity,
            "evidence": evidence,
            "suggested_fix": fix
        }
        if isinstance(page, list):
            if len(page) == 1:
                item["page"] = page[0]
            else:
                item["affected_pages"] = page
        else:
            item["page"] = page

        self.findings.append(item)

    def _format_output(self) -> List[Dict[str, Any]]:
        # Deduplicate identical findings
        unique_findings = []
        seen = set()
        for f in self.findings:
            page_key = tuple(f.get("affected_pages", [])) if "affected_pages" in f else f.get("page", "")
            key = (f["metric"], page_key, f["evidence"])
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)
        return unique_findings
