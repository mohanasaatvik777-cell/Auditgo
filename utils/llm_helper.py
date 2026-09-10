import os
import json
from typing import Optional, List, Dict, Generator, Any
from dotenv import load_dotenv

load_dotenv()

# Candidate models ranked by preference
_QUICK_CANDIDATES = [
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "groq/compound-mini",
]

_DEEP_CANDIDATES = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "groq/compound",
]

# Senior SEO Auditor & Principal Web Engineer Personas
_SYSTEM_QUICK = (
    "You are Auditgo's Senior Technical SEO Auditor and Principal Web Engineer. "
    "You possess deep expertise in Google Search crawling, indexing pipelines, Core Web Vitals, Schema.org, "
    "and on-page architectural SEO.\n\n"
    "Guidelines:\n"
    "1. Grounding: Answer strictly based on the provided website content, SEO audit findings, and NAP consistency report. "
    "Never hallucinate issues or facts not present in the data.\n"
    "2. Style: Authoritative, concise, developer-actionable, and structured using clean Markdown.\n"
    "3. Structure: Provide a direct verdict/answer first, followed by relevant technical evidence (tags, status codes, URLs, or excerpts), "
    "and concrete developer remediation steps where applicable.\n"
    "4. Cite source URLs and exact metrics whenever available."
)

_SYSTEM_DEEP = (
    "You are Auditgo's Principal Technical SEO Architect and Senior Web Auditor with 15+ years of experience "
    "in enterprise search engine optimization, Google Search Console diagnostic triage, Schema.org semantic modeling, "
    "crawl budget optimization, and production web engineering.\n\n"
    "Your objective is to provide a comprehensive, deeply technical, and developer-actionable response grounded in the provided "
    "crawl data, on-page SEO audit findings, NAP report, and site architecture.\n\n"
    "Response Structure (Use Markdown):\n"
    "- ### Executive Verdict: Direct, high-level summary addressing the user's specific query.\n"
    "- ### Technical SEO Analysis & Evidence: Deep dive into the data. Highlight exact metrics, severity levels (CRITICAL, WARNING, OPPORTUNITY), "
    "affected URLs, DOM snippets (e.g. `<title>`, `<meta>`, `<h1>`, canonicals), status codes, or text quotes.\n"
    "- ### Search Engine Impact: Explain precisely how this influences Googlebot crawling, indexation risk, snippet rendering, CTR, or ranking authority.\n"
    "- ### Developer Remediation Roadmap: Step-by-step developer instructions with production-ready code snippets (HTML, JSON-LD, HTTP headers, Nginx/Apache rewrites).\n\n"
    "Rules:\n"
    "1. Never fabricate or speculate beyond the provided audit findings and crawled website text.\n"
    "2. If an issue passed or no defect was detected for a queried metric, clearly report it as healthy/passed.\n"
    "3. Always reference specific URLs and technical evidence from the audit."
)


class LLMHelper:
    def __init__(self):
        self.client       = None   # sync Groq client
        self.async_client = None   # async Groq client
        self.api_key      = ""
        self.quick_model  = os.getenv("GROQ_QUICK_MODEL", "").strip() or "openai/gpt-oss-20b"
        self.deep_model   = os.getenv("GROQ_DEEP_MODEL", "").strip() or "openai/gpt-oss-120b"
        self._models_resolved = False
        self._init_client()

    # ── Initialisation & Model Resolution ─────────────────────────
    def _init_client(self):
        key = os.getenv("GROQ_API_KEY", "").strip()
        if key and key != self.api_key:
            self._build_clients(key)

    def _build_clients(self, key: str):
        self.api_key = key
        try:
            from groq import Groq, AsyncGroq
            self.client       = Groq(api_key=key)
            self.async_client = AsyncGroq(api_key=key)
            self._resolve_models()
        except Exception:
            self.client = self.async_client = None

    def _resolve_models(self):
        """
        Dynamically query active Groq models for this API key
        to prevent 404 Model Not Found errors.
        """
        if not self.client:
            return
        try:
            available = [m.id for m in self.client.models.list().data]
            if not available:
                return

            # Check quick model
            env_quick = os.getenv("GROQ_QUICK_MODEL", "").strip()
            if env_quick and env_quick in available:
                self.quick_model = env_quick
            else:
                for candidate in _QUICK_CANDIDATES:
                    if candidate in available:
                        self.quick_model = candidate
                        break

            # Check deep model
            env_deep = os.getenv("GROQ_DEEP_MODEL", "").strip()
            if env_deep and env_deep in available:
                self.deep_model = env_deep
            else:
                for candidate in _DEEP_CANDIDATES:
                    if candidate in available:
                        self.deep_model = candidate
                        break

            self._models_resolved = True
        except Exception:
            # If network or permissions prevent listing, maintain defaults
            pass

    def set_api_key(self, api_key: str):
        if api_key and api_key.strip():
            os.environ["GROQ_API_KEY"] = api_key.strip()
            self._build_clients(api_key.strip())

    def has_key(self) -> bool:
        if not self.client:
            self._init_client()
        return bool(self.api_key and (self.client or self.async_client))

    # ── SEO fix refinement ─────────────────────────────────────────
    def refine_suggested_fix(self, metric: str, evidence: str, default_fix: str) -> str:
        if not self.client:
            self._init_client()
        if not self.client:
            return default_fix
        try:
            resp = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a principal technical SEO engineer. "
                            "Write exactly ONE concise, developer-actionable sentence specifying the precise fix."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"SEO Issue Metric: '{metric}'.\n"
                            f"Detected Evidence: '{evidence[:220]}'.\n"
                            f"Base Fix Reference: '{default_fix}'.\n"
                            "Deliver ONE crisp, production-ready developer remediation instruction."
                        ),
                    },
                ],
                model=self.quick_model or "openai/gpt-oss-20b",
                max_tokens=90,
                temperature=0.1,
            )
            ans = resp.choices[0].message.content.strip()
            return ans or default_fix
        except Exception:
            return default_fix

    # ── Streaming answer (yields text tokens) ─────────────────────
    def stream_answer(
        self,
        query: str,
        sources: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
        deep: bool = False,
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> Generator[str, None, None]:
        """
        Sync generator yielding raw tokens from Groq.
        Grounded in website content, SEO audit findings, and NAP reports.
        """
        if not self.client:
            self._init_client()
        if not self.client:
            yield self._fallback_answer(query, sources, audit_context)
            return

        model   = self.deep_model if deep else self.quick_model
        max_tok = 900 if deep else 550
        system  = _SYSTEM_DEEP if deep else _SYSTEM_QUICK

        context_block = self._build_context(sources, audit_context)
        messages      = self._build_messages(system, query, context_block, conversation_history)

        try:
            stream = self.client.chat.completions.create(
                messages=messages,
                model=model,
                max_tokens=max_tok,
                temperature=0.2,
                stream=True,
            )
            for chunk in stream:
                token = (chunk.choices[0].delta.content or "")
                if token:
                    yield token
        except Exception as e:
            # Try secondary model fallback if first failed
            alt_model = self.quick_model if model == self.deep_model else self.deep_model
            try:
                stream = self.client.chat.completions.create(
                    messages=messages,
                    model=alt_model,
                    max_tokens=max_tok,
                    temperature=0.2,
                    stream=True,
                )
                for chunk in stream:
                    token = (chunk.choices[0].delta.content or "")
                    if token:
                        yield token
            except Exception:
                yield self._fallback_answer(query, sources, audit_context)

    # ── Non-streaming synthesis ───────────────────────────────────
    def synthesize_answer(
        self,
        query: str,
        sources: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
        deep: bool = False,
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.client:
            self._init_client()
        if not self.client:
            return self._fallback_answer(query, sources, audit_context)

        model   = self.deep_model if deep else self.quick_model
        max_tok = 800 if deep else 450
        system  = _SYSTEM_DEEP if deep else _SYSTEM_QUICK

        context_block = self._build_context(sources, audit_context)
        messages      = self._build_messages(system, query, context_block, conversation_history)

        try:
            resp   = self.client.chat.completions.create(
                messages=messages,
                model=model,
                max_tokens=max_tok,
                temperature=0.2,
            )
            answer = resp.choices[0].message.content.strip()
            return answer or self._fallback_answer(query, sources, audit_context)
        except Exception:
            return self._fallback_answer(query, sources, audit_context)

    # ── Context & Message Construction ─────────────────────────────
    def _build_context(
        self,
        sources: List[Dict],
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        sections = []

        # 1. Site Audit Context & Findings
        if audit_context:
            target_url = audit_context.get("url", "")
            stats = audit_context.get("crawl_stats", {})
            findings = audit_context.get("audit", [])
            nap = audit_context.get("nap_report", [])

            audit_lines = ["### AUDIT & CRAWL DATA FOR: " + (target_url or "Target Site")]
            if stats:
                audit_lines.append(
                    f"- Pages Crawled: {stats.get('crawled', 0)} | Skipped: {stats.get('skipped', 0)}"
                )

            if findings:
                high_count = sum(1 for f in findings if (f.get("severity") or "").lower() == "high")
                med_count  = sum(1 for f in findings if (f.get("severity") or "").lower() == "medium")
                low_count  = sum(1 for f in findings if (f.get("severity") or "").lower() == "low")
                audit_lines.append(
                    f"- Total Detected Findings: {len(findings)} ({high_count} High, {med_count} Medium, {low_count} Low)"
                )
                audit_lines.append("Key Detected SEO Findings:")
                # Include up to 15 relevant findings
                for f in findings[:15]:
                    pg = f.get("affected_pages") or f.get("page")
                    pg_str = ", ".join(pg) if isinstance(pg, list) else str(pg)
                    audit_lines.append(
                        f"  * [{f.get('severity','').upper()}] {f.get('metric')}: {f.get('evidence')} "
                        f"| Page: {pg_str} | Fix: {f.get('suggested_fix')}"
                    )
            else:
                audit_lines.append("- SEO Findings: Clean audit. No major on-page violations detected.")

            if nap:
                audit_lines.append("NAP Consistency Summary:")
                for n in nap:
                    verdict = n.get("verdict", "unknown")
                    vals = ", ".join(n.get("values", [])[:3])
                    audit_lines.append(f"  * {n.get('field')}: Verdict={verdict}, Found=[{vals}], Confidence={n.get('confidence')}")

            sections.append("\n".join(audit_lines))

        # 2. Crawled Page Passages / Sources
        if sources:
            source_lines = ["### RELEVANT WEBSITE CONTENT PASSAGES:"]
            for i, s in enumerate(sources[:5], 1):
                url = s.get("url", "")
                excerpt = s.get("excerpt", "")
                metric_tag = f" ({s.get('metric')})" if s.get("metric") else ""
                source_lines.append(f"[Source {i}{metric_tag}] URL: {url}\n\"{excerpt}\"")
            sections.append("\n\n".join(source_lines))

        return "\n\n" + ("\n\n---\n\n".join(sections)) if sections else "No specific site context available."

    def _build_messages(
        self,
        system: str,
        query: str,
        context_block: str,
        history: Optional[List[Dict]],
    ) -> List[Dict]:
        msgs = [{"role": "system", "content": system}]
        for turn in (history or [])[-6:]:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                msgs.append({"role": turn["role"], "content": turn["content"]})
        msgs.append({
            "role": "user",
            "content": (
                f"User Question:\n{query}\n\n"
                f"Verified Site Context, Audit Results & Website Excerpts:\n{context_block}"
            ),
        })
        return msgs

    def _fallback_answer(
        self,
        query: str,
        sources: List[Dict],
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines = [f"### Senior SEO Audit Assessment for: *\"{query}\"*\n"]

        # Check if query is about SEO issues
        if audit_context and audit_context.get("audit"):
            findings = audit_context["audit"]
            lines.append(f"**Audit Findings Overview ({len(findings)} total detected):**\n")
            for f in findings[:5]:
                lines.append(
                    f"- **[{f.get('severity', 'LOW').upper()}] {f.get('metric')}**: {f.get('evidence')}\n"
                    f"  *Recommended Fix:* {f.get('suggested_fix')}"
                )
            return "\n".join(lines)

        if not sources:
            return (
                f"No verified passages matching \"{query}\" were found in the crawled website data or audit logs. "
                "Try inquiring about specific on-page SEO metrics (e.g., titles, meta descriptions, headings, broken links) "
                "or NAP consistency."
            )

        lines.append("Here is the relevant information extracted from the website:\n")
        for i, s in enumerate(sources[:3], 1):
            raw_url = s.get("url", "")
            clean = self._clean_url_display(raw_url)
            lines.append(f"{i}. **From [{clean}]({raw_url})**:\n> \"{s.get('excerpt','')}\"")
        return "\n".join(lines)

    def _clean_url_display(self, url: str) -> str:
        if not url:
            return "Site Page"
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            path = p.path
            if len(path) > 35:
                path = path[:18] + "…" + path[-12:]
            return f"{p.netloc}{path}" if path and path != "/" else p.netloc
        except Exception:
            return url[:45] + ("…" if len(url) > 45 else "")


llm_helper = LLMHelper()
