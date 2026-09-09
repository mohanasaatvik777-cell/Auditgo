import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from crawler.url_utils import normalize_url, is_same_registrable_domain, is_safe_url

class CrawledPage:
    def __init__(self, original_url: str, final_url: str, status_code: int, depth: int, headers: dict, content: bytes, text: str):
        self.original_url = original_url
        self.final_url = final_url
        self.status_code = status_code
        self.depth = depth
        self.headers = headers
        self.content = content
        self.text = text
        self.links = []
        self.is_broken = status_code >= 400 or status_code == 0
        self.content_type = headers.get("content-type", "").lower()

class Crawler:
    def __init__(self, start_url: str, max_pages: int = 150, max_depth: int = 4, per_request_timeout: float = 10.0, total_timeout: float = 120.0, allow_localhost: bool = False):
        self.start_url = normalize_url(start_url)
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.per_request_timeout = per_request_timeout
        self.total_timeout = total_timeout
        self.allow_localhost = allow_localhost or ("127.0.0.1" in start_url or "localhost" in start_url)
        
        self.visited_urls = set()
        self.crawled_pages = {}  # url -> CrawledPage
        self.skipped_pages = set() # urls skipped due to budget/depth/robots
        self.sitemap_urls = set()
        self.sitemap_entries = set() # urls found inside sitemap
        self.robots_parser = None
        
    def _init_robots(self, client: httpx.Client):
        parsed = urlparse(self.start_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            resp = client.get(robots_url, timeout=self.per_request_timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                for line in resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        s_url = line.split(":", 1)[1].strip()
                        if s_url:
                            self.sitemap_urls.add(s_url)
                self.robots_parser = rp
            else:
                # 404 or non-200 means no restrictions
                self.robots_parser = None
        except Exception:
            self.robots_parser = None
        
        if not self.sitemap_urls:
            default_sitemap = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
            self.sitemap_urls.add(default_sitemap)

    def _fetch_sitemaps(self, client: httpx.Client):
        for s_url in list(self.sitemap_urls):
            try:
                resp = client.get(s_url, timeout=self.per_request_timeout)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.content, "xml")
                    # Check for loc tags in sitemapindex or urlset
                    locs = soup.find_all("loc")
                    for loc in locs:
                        loc_text = loc.get_text().strip()
                        if loc_text:
                            if "sitemap" in loc_text.lower() and loc_text != s_url:
                                # Sitemap index recursive fetch
                                try:
                                    sub_resp = client.get(loc_text, timeout=self.per_request_timeout)
                                    if sub_resp.status_code == 200:
                                        sub_soup = BeautifulSoup(sub_resp.content, "xml")
                                        for sub_loc in sub_soup.find_all("loc"):
                                            if sub_loc.get_text().strip():
                                                self.sitemap_entries.add(normalize_url(sub_loc.get_text().strip()))
                                except Exception:
                                    pass
                            else:
                                self.sitemap_entries.add(normalize_url(loc_text))
            except Exception:
                pass

    def crawl(self) -> dict:
        start_time = time.time()
        queue = [(self.start_url, 0)]
        
        headers = {
            "User-Agent": "SEOAuditAgent/1.0 (+https://github.com/seo-audit-agent)"
        }
        
        with httpx.Client(headers=headers, follow_redirects=True, timeout=self.per_request_timeout) as client:
            self._init_robots(client)
            self._fetch_sitemaps(client)
            
            while queue:
                if len(self.crawled_pages) >= self.max_pages:
                    # Mark remaining queue items as skipped due to budget
                    for u, _ in queue:
                        self.skipped_pages.add(u)
                    break
                    
                if time.time() - start_time > self.total_timeout:
                    for u, _ in queue:
                        self.skipped_pages.add(u)
                    break
                    
                curr_url, depth = queue.pop(0)
                norm_curr_url = normalize_url(curr_url)
                
                if norm_curr_url in self.visited_urls:
                    continue
                self.visited_urls.add(norm_curr_url)
                
                if not is_safe_url(norm_curr_url, self.allow_localhost):
                    continue
                    
                if not is_same_registrable_domain(self.start_url, norm_curr_url):
                    continue
                    
                if self.robots_parser and not self.robots_parser.can_fetch("SEOAuditAgent", norm_curr_url):
                    self.skipped_pages.add(norm_curr_url)
                    continue
                    
                if depth > self.max_depth:
                    self.skipped_pages.add(norm_curr_url)
                    continue
                    
                try:
                    resp = client.get(norm_curr_url)
                    final_url = normalize_url(str(resp.url))
                    
                    page = CrawledPage(
                        original_url=norm_curr_url,
                        final_url=final_url,
                        status_code=resp.status_code,
                        depth=depth,
                        headers=dict(resp.headers),
                        content=resp.content,
                        text=resp.text
                    )
                    
                    self.crawled_pages[norm_curr_url] = page
                    if final_url != norm_curr_url:
                        self.crawled_pages[final_url] = page
                        
                    if resp.status_code == 200 and "text/html" in page.content_type:
                        soup = BeautifulSoup(resp.content, "lxml")
                        for a in soup.find_all("a", href=True):
                            href = a["href"].strip()
                            if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                                abs_url = normalize_url(urljoin(final_url, href))
                                page.links.append(abs_url)
                                if (abs_url not in self.visited_urls and 
                                    is_same_registrable_domain(self.start_url, abs_url) and 
                                    is_safe_url(abs_url, self.allow_localhost)):
                                    queue.append((abs_url, depth + 1))
                                    
                except Exception as e:
                    page = CrawledPage(
                        original_url=norm_curr_url,
                        final_url=norm_curr_url,
                        status_code=0,
                        depth=depth,
                        headers={},
                        content=b"",
                        text=""
                    )
                    self.crawled_pages[norm_curr_url] = page
                    
        return {
            "start_url": self.start_url,
            "crawled_pages": self.crawled_pages,
            "skipped_pages": self.skipped_pages,
            "sitemap_entries": self.sitemap_entries,
            "sitemap_urls": self.sitemap_urls
        }
