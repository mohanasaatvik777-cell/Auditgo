import re
import json
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup
from rank_bm25 import BM25Okapi
from crawler.fetcher import CrawledPage
from crawler.parser import parse_html
from utils.llm_helper import llm_helper


class GroundedQAEngine:
    """
    Multi-source grounded Q&A engine:
    1. Indexes crawled page content (titles, meta descriptions, headings, visible body text)
    2. Indexes On-Page SEO audit findings (metrics, severity, evidence, fixes)
    3. Indexes NAP consistency reports (business name, address, phone numbers, verdicts)
    4. Provides intelligent retrieval and synthesis via Groq with Senior SEO Auditor authority.
    """

    def __init__(
        self,
        crawl_data: Dict[str, Any],
        score_threshold: float = 0.25,
        audit_data: Optional[Dict[str, Any]] = None,
    ):
        self.crawl_data = crawl_data or {}
        self.crawled_pages: Dict[str, CrawledPage] = self.crawl_data.get("crawled_pages", {})
        
        # Merge audit context from audit_data parameter or from crawl_data dictionary
        combined_audit = audit_data or self.crawl_data
        self.audit_findings: List[Dict] = combined_audit.get("audit") or []
        self.nap_report: List[Dict] = combined_audit.get("nap_report") or []
        self.crawl_stats: Dict[str, Any] = combined_audit.get("crawl_stats") or self.crawl_data.get("crawl_stats", {})
        self.target_url: str = combined_audit.get("url") or self.crawl_data.get("url", "")
        if not self.target_url and self.crawled_pages:
            self.target_url = next(iter(self.crawled_pages.keys()))

        self.score_threshold = score_threshold
        self.passages: List[Dict] = []
        self._index_built = False

    def get_audit_context(self) -> Dict[str, Any]:
        """Return structured site context for LLM grounding."""
        return {
            "url":         self.target_url,
            "crawl_stats": self.crawl_stats,
            "audit":       self.audit_findings,
            "nap_report":  self.nap_report,
        }

    # ────────────────────────────────────────────────────
    # Fast passage retrieval — used by streaming endpoint
    # ────────────────────────────────────────────────────
    def get_passages(
        self,
        query: str,
        top_n: int = 5,
        allow_fallback: bool = True,
        conversation_history: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """
        Return top-N BM25 and intent-ranked passages with conversational memory support.
        Builds the unified index once per engine instance.
        """
        if not query or not query.strip():
            return []
        if not self._index_built:
            self._build_index()
        if not self.passages:
            return self._get_overview_passages(top_n) if allow_fallback else []

        tokenized_query = self._tokenize(query)
        q_lower = query.lower()

        # Conversational query expansion for follow-up questions (e.g., "tell me more about it?")
        conversational_triggers = [
            "tell me more", "more about", "explain", "elaborate", "what else",
            "how about", "why", "how so", "what do you mean", "how do i",
            "tell me about it", "what is it", "how does that work", "fix it",
            "more details", "expand", "about that", "why is that"
        ]
        q_clean = re.sub(r'[^\w\s]', '', q_lower).strip()
        is_followup = any(trig in q_clean for trig in conversational_triggers) or len(tokenized_query) <= 3
        if is_followup and conversation_history:
            history_text = ""
            for msg in reversed(conversation_history[-4:]):
                c = msg.get("content", "")
                if c:
                    history_text += " " + c
            clean_hist = re.sub(r'[^\w\s]', ' ', history_text.lower())
            stop_words = {
                "the", "and", "for", "that", "this", "with", "from", "your", "have",
                "what", "here", "are", "about", "tell", "more", "can", "you", "was",
                "not", "all", "our", "will", "get", "has", "just", "out", "how", "did"
            }
            hist_words = [w for w in clean_hist.split() if len(w) >= 3 and w not in stop_words]
            unique_terms = []
            for w in hist_words:
                if w not in unique_terms and w not in tokenized_query:
                    unique_terms.append(w)
                if len(unique_terms) >= 6:
                    break
            if unique_terms:
                tokenized_query = tokenized_query + unique_terms

        if not tokenized_query:
            return self._get_overview_passages(top_n) if allow_fallback else []

        # Intent detection
        is_seo_query = any(w in q_lower for w in [
            "seo", "issue", "finding", "audit", "title", "meta", "description",
            "heading", "h1", "h2", "link", "broken", "canonical", "noindex",
            "robot", "sitemap", "alt", "image", "severity", "fix", "score",
            "rank", "crawl", "duplicate", "schema", "structured data", "error"
        ])
        is_nap_query = any(w in q_lower for w in [
            "phone", "address", "nap", "contact", "call", "location", "email",
            "office", "hours", "consistency", "mismatch", "business name"
        ])
        is_overview_query = any(w in q_lower for w in [
            "overview", "summary", "summarize", "about", "what is this",
            "what does this", "tell me about", "who is", "services", "products"
        ])

        corpus = [p["tokens"] for p in self.passages]
        bm25   = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenized_query)

        query_set = set(tokenized_query)
        ranked = []
        for idx, passage in enumerate(self.passages):
            bm_score    = float(scores[idx])
            passage_set = set(passage["tokens"])
            overlap     = len(query_set & passage_set) / len(query_set) if query_set else 0.0
            
            # Boost based on query intent matching passage type
            boost = 0.0
            if is_seo_query and passage.get("is_audit"):
                boost += 3.5
            elif is_nap_query and passage.get("is_nap"):
                boost += 3.5
            elif passage.get("is_meta"):
                boost += 1.0

            combined = bm_score + (overlap * 2.5) + boost
            if (len(query_set & passage_set) >= 1 or boost > 2.0) and combined >= self.score_threshold:
                ranked.append((combined, passage))

        ranked.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, passage in ranked[:top_n * 3]:
            # For audit and nap findings, passage text is already verified from crawl analysis
            if passage.get("is_audit") or passage.get("is_nap"):
                results.append({
                    "url":          passage["url"],
                    "excerpt":      passage["text"],
                    "score":        round(score, 4),
                    "metric":       passage.get("metric"),
                    "start_offset": passage.get("start_offset"),
                    "end_offset":   passage.get("end_offset"),
                })
            else:
                verified = self._verify_excerpt(passage["text"], passage.get("raw_html", ""))
                if verified:
                    results.append({
                        "url":          passage["url"],
                        "excerpt":      verified,
                        "score":        round(score, 4),
                        "metric":       None,
                        "start_offset": passage.get("start_offset"),
                        "end_offset":   passage.get("end_offset"),
                    })
            if len(results) >= top_n:
                break

        # Fallback to structured overview if query yielded no direct matches
        if not results and allow_fallback:
            return self._get_overview_passages(top_n)

        return results

    def _get_overview_passages(self, top_n: int = 5) -> List[Dict]:
        """
        Construct balanced fallback overview passages including top SEO issues,
        NAP status, and core page descriptions when keyword retrieval finds 0 direct matches.
        """
        overview = []
        
        # 1. Include top SEO findings if available
        for f in self.audit_findings[:2]:
            pg = f.get("affected_pages") or f.get("page") or self.target_url
            pg_url = pg[0] if isinstance(pg, list) and pg else str(pg)
            overview.append({
                "url":          pg_url,
                "excerpt":      f"SEO Finding [{f.get('severity','').upper()}]: {f.get('metric')} - {f.get('evidence')} | Fix: {f.get('suggested_fix')}",
                "score":        1.5,
                "metric":       f.get("metric"),
                "start_offset": 0,
                "end_offset":   0,
            })

        # 2. Include core page passages
        for p in self.passages:
            if len(overview) >= top_n:
                break
            if p.get("is_audit") or p.get("is_nap"):
                continue
            verified = self._verify_excerpt(p["text"], p.get("raw_html", ""))
            if verified:
                overview.append({
                    "url":          p["url"],
                    "excerpt":      verified,
                    "score":        1.0,
                    "metric":       None,
                    "start_offset": p.get("start_offset"),
                    "end_offset":   p.get("end_offset"),
                })

        return overview[:top_n]

    # ────────────────────────────────────────────────────
    # Full pipeline (used by /api/audit and CLI)
    # ────────────────────────────────────────────────────
    def answer_query(
        self,
        query: Optional[str],
        conversation_history: Optional[List[Dict]] = None,
        deep: bool = False,
    ) -> Dict[str, Any]:
        if not query or not query.strip():
            return self._null_result(query or "", conversation_history)

        top_n   = 5 if deep else 3
        sources = self.get_passages(
            query, top_n=top_n, allow_fallback=False, conversation_history=conversation_history
        )

        if not sources:
            return self._null_result(query, conversation_history)

        audit_context = self.get_audit_context()
        synthesized = llm_helper.synthesize_answer(
            query, sources, conversation_history, deep=deep, audit_context=audit_context
        )

        history = list(conversation_history or [])
        history.append({"role": "user",      "content": query})
        history.append({"role": "assistant", "content": synthesized or sources[0]["excerpt"]})

        best = sources[0]
        return {
            "query":                query,
            "answer":               synthesized,
            "excerpt":              best["excerpt"],
            "url":                  best["url"],
            "confidence":           round(min(best["score"] / 10.0, 1.0), 2),
            "sources":              sources,
            "synthesized":          synthesized is not None,
            "conversation_history": history,
        }

    # ────────────────────────────────────────────────────
    # Index building (Content + SEO Findings + NAP)
    # ────────────────────────────────────────────────────
    def _build_index(self):
        self.passages = []

        # 1. Index SEO Audit Findings
        for finding in self.audit_findings:
            metric   = finding.get("metric", "seo_issue")
            severity = finding.get("severity", "medium").upper()
            evidence = finding.get("evidence", "")
            fix      = finding.get("suggested_fix", "")
            page     = finding.get("affected_pages") or finding.get("page") or self.target_url
            page_url = page[0] if isinstance(page, list) and page else str(page)

            text = f"SEO Audit Finding [{severity}] {metric}: {evidence} Recommended Fix: {fix}"
            tokens = self._tokenize(text)
            if tokens:
                self.passages.append({
                    "url":          page_url,
                    "raw_html":     "",
                    "text":         text,
                    "tokens":       tokens,
                    "metric":       metric,
                    "is_audit":     True,
                    "start_offset": 0,
                    "end_offset":   len(text),
                })

        # 2. Index NAP Consistency Data
        for nap in self.nap_report:
            field      = nap.get("field", "")
            verdict    = nap.get("verdict", "")
            confidence = nap.get("confidence", "")
            values     = ", ".join(nap.get("values", []))
            normalized = ", ".join(nap.get("normalized_values", []))

            text = f"NAP Report for {field}: Verdict is {verdict} (Confidence: {confidence}). Values found across website: {values}. Normalized: {normalized}."
            tokens = self._tokenize(text)
            if tokens:
                self.passages.append({
                    "url":          self.target_url,
                    "raw_html":     "",
                    "text":         text,
                    "tokens":       tokens,
                    "metric":       f"nap_{field}",
                    "is_nap":       True,
                    "start_offset": 0,
                    "end_offset":   len(text),
                })

        # 3. Index Crawled Pages (Meta + Headings + Visible Body Text)
        for url, page in self.crawled_pages.items():
            if page.status_code != 200 or not page.text:
                continue

            # Extract Title & Meta Description as high-value passages
            try:
                soup = BeautifulSoup(page.text, "lxml")
                title_tag = soup.find("title")
                if title_tag and title_tag.get_text().strip():
                    t_text = f"Page Title for {url}: {title_tag.get_text().strip()}"
                    t_toks = self._tokenize(t_text)
                    if t_toks:
                        self.passages.append({
                            "url":          url,
                            "raw_html":     page.text,
                            "text":         t_text,
                            "tokens":       t_toks,
                            "is_meta":      True,
                            "start_offset": 0,
                            "end_offset":   len(t_text),
                        })

                meta_desc = soup.find("meta", attrs={"name": lambda n: n and n.lower() == "description"})
                if meta_desc and meta_desc.get("content", "").strip():
                    d_text = f"Meta Description for {url}: {meta_desc.get('content', '').strip()}"
                    d_toks = self._tokenize(d_text)
                    if d_toks:
                        self.passages.append({
                            "url":          url,
                            "raw_html":     page.text,
                            "text":         d_text,
                            "tokens":       d_toks,
                            "is_meta":      True,
                            "start_offset": 0,
                            "end_offset":   len(d_text),
                        })
            except Exception:
                pass

            # Body chunks from parser
            parsed = parse_html(page.text)
            for chunk in parsed.chunks:
                text = chunk.text.strip()
                if len(text) < 15:
                    continue
                tokens = self._tokenize(text)
                if tokens:
                    self.passages.append({
                        "url":          url,
                        "raw_html":     page.text,
                        "text":         text,
                        "tokens":       tokens,
                        "start_offset": chunk.start_offset,
                        "end_offset":   chunk.end_offset,
                    })

        self._index_built = True

    # ────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────
    def _tokenize(self, text: str) -> List[str]:
        clean = re.sub(r'[^\w\s]', ' ', text.lower())
        return [w for w in clean.split() if len(w) >= 2]

    def _verify_excerpt(self, excerpt: str, raw_html: str) -> Optional[str]:
        if not excerpt:
            return None
        if not raw_html:
            return excerpt
        if excerpt in raw_html:
            return excerpt
        soup      = BeautifulSoup(raw_html, "lxml")
        full_text = soup.get_text(separator=" ")
        if excerpt in full_text:
            return excerpt
        norm_e  = " ".join(excerpt.split())
        norm_ft = " ".join(full_text.split())
        if norm_e in norm_ft:
            return excerpt
        return None

    def _null_result(self, query: str, history: Optional[List[Dict]]) -> Dict[str, Any]:
        return {
            "query":                query,
            "answer":               None,
            "excerpt":              None,
            "url":                  None,
            "confidence":           0.0,
            "sources":              [],
            "synthesized":          False,
            "conversation_history": list(history or []),
        }
