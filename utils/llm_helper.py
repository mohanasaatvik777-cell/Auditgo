import os
import json
from typing import Optional, List, Dict, Generator
from dotenv import load_dotenv

load_dotenv()

# Models
_QUICK_MODEL = "llama-3.1-8b-instant"     # ~0.5s first token
_DEEP_MODEL  = "llama-3.3-70b-versatile"  # ~1s first token, much smarter

# System prompts
_SYSTEM_QUICK = (
    "You are Auditgo, an AI intelligence assistant that analyzes website content for users. "
    "Carefully read and analyze all provided website excerpts and metadata to answer the user's question accurately and insightfully. "
    "Do not hallucinate facts outside the website context. Give a direct, helpful, well-structured answer in 2-4 sentences and cite relevant source URLs."
)

_SYSTEM_DEEP = (
    "You are Auditgo's senior research analyst. You analyze website content and data with depth and professional precision.\n"
    "Rules:\n"
    "1. Thoroughly analyze the provided website excerpts, metadata, and page context to answer the user's question.\n"
    "2. Structure your answer clearly: Direct answer → Detailed context & analysis → Key details.\n"
    "3. Synthesize multiple page sources cohesively.\n"
    "4. Explicitly cite source URLs.\n"
    "5. Maintain a professional tone suitable for business analysts and web engineering professionals."
)


class LLMHelper:
    def __init__(self):
        self.client       = None   # sync Groq client
        self.async_client = None   # async Groq client
        self.api_key      = ""
        self._init_client()

    # ── Initialisation ─────────────────────────────────────────
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
        except Exception:
            self.client = self.async_client = None

    def set_api_key(self, api_key: str):
        if api_key and api_key.strip():
            os.environ["GROQ_API_KEY"] = api_key.strip()
            self._build_clients(api_key.strip())

    def has_key(self) -> bool:
        if not self.client:
            self._init_client()
        return bool(self.api_key and (self.client or self.async_client))

    # ── SEO fix refinement (unchanged) ────────────────────────
    def refine_suggested_fix(self, metric: str, evidence: str, default_fix: str) -> str:
        if not self.client:
            self._init_client()
        if not self.client:
            return default_fix
        try:
            resp = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a senior SEO engineer. Reply in exactly one sentence."},
                    {"role": "user",   "content": (
                        f"SEO issue: '{metric}'. Evidence: '{evidence[:200]}'. "
                        f"Write ONE concise, developer-actionable sentence fix. Reference: {default_fix}"
                    )},
                ],
                model=_DEEP_MODEL,
                max_tokens=80,
                temperature=0.1,
            )
            return resp.choices[0].message.content.strip() or default_fix
        except Exception:
            return default_fix

    # ── Streaming answer (yields text tokens) ─────────────────
    def stream_answer(
        self,
        query: str,
        sources: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
        deep: bool = False,
    ) -> Generator[str, None, None]:
        """
        Sync generator that yields raw text tokens from Groq.
        Use deep=False for quick (~1-3s), deep=True for thorough (~5-10s).
        Falls back to yielding a formatted fallback string if Groq is unavailable.
        """
        if not self.client:
            self._init_client()
        if not self.client:
            yield self._fallback_answer(query, sources)
            return

        model     = _DEEP_MODEL  if deep else _QUICK_MODEL
        max_tok   = 500          if deep else 250
        top_n     = 5            if deep else 3
        system    = _SYSTEM_DEEP if deep else _SYSTEM_QUICK

        context_block = self._build_context(sources[:top_n])
        messages      = self._build_messages(system, query, context_block, conversation_history)

        try:
            stream = self.client.chat.completions.create(
                messages=messages,
                model=model,
                max_tokens=max_tok,
                temperature=0.15,
                stream=True,
            )
            for chunk in stream:
                token = (chunk.choices[0].delta.content or "")
                if token:
                    yield token
        except Exception as e:
            yield self._fallback_answer(query, sources)

    # ── Non-streaming synthesis (used by run_agent for audit) ──
    def synthesize_answer(
        self,
        query: str,
        sources: List[Dict],
        conversation_history: Optional[List[Dict]] = None,
        deep: bool = False,
    ) -> Optional[str]:
        if not self.client:
            self._init_client()
        if not self.client:
            return self._fallback_answer(query, sources)

        model   = _DEEP_MODEL  if deep else _QUICK_MODEL
        max_tok = 400          if deep else 250
        top_n   = 5            if deep else 3
        system  = _SYSTEM_DEEP if deep else _SYSTEM_QUICK

        context_block = self._build_context(sources[:top_n])
        messages      = self._build_messages(system, query, context_block, conversation_history)

        try:
            resp   = self.client.chat.completions.create(
                messages=messages, model=model,
                max_tokens=max_tok, temperature=0.15,
            )
            answer = resp.choices[0].message.content.strip()
            return answer or self._fallback_answer(query, sources)
        except Exception:
            return self._fallback_answer(query, sources)

    # ── Helpers ────────────────────────────────────────────────
    def _build_context(self, sources: List[Dict]) -> str:
        parts = []
        for i, s in enumerate(sources, 1):
            parts.append(f"[Source {i}] {s.get('url','')}\n\"{s.get('excerpt','')}\"")
        return "\n\n".join(parts)

    def _build_messages(
        self,
        system: str,
        query: str,
        context_block: str,
        history: Optional[List[Dict]],
    ) -> List[Dict]:
        msgs = [{"role": "system", "content": system}]
        # Last 6 history turns for context memory
        for turn in (history or [])[-6:]:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                msgs.append({"role": turn["role"], "content": turn["content"]})
        msgs.append({
            "role": "user",
            "content": (
                f"User Question: {query}\n\n"
                f"Website Content & Excerpts:\n{context_block}"
            ),
        })
        return msgs

    def _fallback_answer(self, query: str, sources: List[Dict]) -> str:
        if not sources:
            return f'No relevant content found on the website for "{query}".'
        lines = [f'Here is what the website context says regarding "{query}":\n']
        for i, s in enumerate(sources[:3], 1):
            lines.append(f"{i}. From {s.get('url','')}:\n   \"{s.get('excerpt','')}\"")
        return "\n".join(lines)


llm_helper = LLMHelper()

