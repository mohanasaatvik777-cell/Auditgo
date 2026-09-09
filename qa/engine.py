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
    Two-tier grounded Q&A:
    - get_passages(query, top_n)  → fast BM25 retrieval only
    - answer_query(...)           → full pipeline with Groq synthesis
    """

    def __init__(self, crawl_data: Dict[str, Any], score_threshold: float = 0.3):
        self.crawled_pages: Dict[str, CrawledPage] = crawl_data.get("crawled_pages", {})
        self.score_threshold = score_threshold
        self.passages: List[Dict] = []
        self._index_built = False

    # ────────────────────────────────────────────────────
    # Fast passage retrieval — used by streaming endpoint
    # ────────────────────────────────────────────────────
    def get_passages(self, query: str, top_n: int = 5) -> List[Dict]:
        """
        Return top-N BM25-ranked, verbatim-verified passages.
        Builds the index only once per engine instance.
        """
        if not query or not query.strip():
            return []
        if not self._index_built:
            self._build_index()
        if not self.passages:
            return []

        tokenized_query = self._tokenize(query)
        if not tokenized_query:
            return []

        corpus = [p["tokens"] for p in self.passages]
        bm25   = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenized_query)

        query_set = set(tokenized_query)
        ranked = []
        for idx, passage in enumerate(self.passages):
            bm_score    = float(scores[idx])
            passage_set = set(passage["tokens"])
            overlap     = len(query_set & passage_set) / len(query_set) if query_set else 0.0
            combined    = bm_score + (overlap * 2.0)
            if len(query_set & passage_set) >= 1 and combined >= self.score_threshold:
                ranked.append((combined, passage))

        ranked.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, passage in ranked[:top_n * 3]:  # over-sample then verify
            verified = self._verify_excerpt(passage["text"], passage["raw_html"])
            if verified:
                results.append({
                    "url":          passage["url"],
                    "excerpt":      verified,
                    "score":        round(score, 4),
                    "start_offset": passage.get("start_offset"),
                    "end_offset":   passage.get("end_offset"),
                })
            if len(results) >= top_n:
                break

        return results

    # ────────────────────────────────────────────────────
    # Full pipeline (used by /api/audit)
    # ────────────────────────────────────────────────────
    def answer_query(
        self,
        query: Optional[str],
        conversation_history: Optional[List[Dict]] = None,
        deep: bool = False,
    ) -> Dict[str, Any]:
        if not query or not query.strip():
            return self._null_result(query or "", conversation_history)

        top_n   = 5 if deep else 2
        sources = self.get_passages(query, top_n=top_n)

        if not sources:
            return self._null_result(query, conversation_history)

        synthesized = llm_helper.synthesize_answer(
            query, sources, conversation_history, deep=deep
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
    # Index building
    # ────────────────────────────────────────────────────
    def _build_index(self):
        self.passages = []
        for url, page in self.crawled_pages.items():
            if page.status_code != 200 or not page.text:
                continue
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
        if not excerpt or not raw_html:
            return None
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
