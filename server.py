import os
import json
import asyncio
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict

from run_agent import run_agent
from utils.llm_helper import llm_helper
from qa.engine import GroundedQAEngine

app = FastAPI(title="Auditgo — AI-Powered SEO Audit Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Multi-Tenant Session Management ───────────────────────────────────────────
class SessionStore:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.crawls: Dict[str, dict] = {}
        self.chat_histories: Dict[str, List[Dict]] = {}

class MultiTenantSessionManager:
    def __init__(self, max_sessions: int = 100):
        self.sessions: Dict[str, SessionStore] = {}
        self.max_sessions = max_sessions

    def get_session(self, session_id: Optional[str]) -> SessionStore:
        sid = (session_id or "default_session").strip()
        if sid not in self.sessions:
            if len(self.sessions) >= self.max_sessions:
                # Prune oldest session if max capacity reached
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[sid] = SessionStore(sid)
        return self.sessions[sid]

session_manager = MultiTenantSessionManager()

# Global fallback cache for legacy/CLI access
_crawl_cache: Dict[str, dict] = {}
MAX_CACHE = 10

def _cache_key(url: str) -> str:
    return url.strip().rstrip("/").lower()

def _store_global_crawl(url: str, crawl_data: dict):
    key = _cache_key(url)
    _crawl_cache[key] = crawl_data
    if len(_crawl_cache) > MAX_CACHE:
        del _crawl_cache[next(iter(_crawl_cache))]


# ── Models ─────────────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    url: str
    query: Optional[str] = None
    output_dir: Optional[str] = "outputs"
    session_id: Optional[str] = "default_session"

class ChatStreamRequest(BaseModel):
    url: str
    question: str
    conversation_history: Optional[List[Dict]] = None
    deep: Optional[bool] = False
    session_id: Optional[str] = "default_session"

class ClearChatRequest(BaseModel):
    url: str
    session_id: Optional[str] = "default_session"


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status":          "ok",
        "app":             "Auditgo",
        "groq_key":        llm_helper.has_key(),
        "quick_model":     llm_helper.quick_model,
        "deep_model":      llm_helper.deep_model,
        "active_sessions": len(session_manager.sessions),
    }


@app.post("/api/audit")
async def execute_audit(req: AuditRequest, x_session_id: Optional[str] = Header(None)):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Target URL is required")

    session_id = x_session_id or req.session_id or "default_session"
    session_store = session_manager.get_session(session_id)
    url_key = _cache_key(req.url)

    try:
        loop    = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, run_agent,
            req.url.strip(), req.query,
            req.output_dir or "outputs", [],
        )
        crawl_data = results.pop("_crawl_data", None)
        if crawl_data:
            # Ensure full audit results and stats remain attached in session crawl cache
            crawl_data.setdefault("audit", results.get("audit", []))
            crawl_data.setdefault("nap_report", results.get("nap_report", []))
            crawl_data.setdefault("crawl_stats", results.get("crawl_stats", {}))
            crawl_data.setdefault("url", req.url.strip())
            session_store.crawls[url_key] = crawl_data
            _store_global_crawl(req.url, crawl_data)

        return JSONResponse(content={
            "status": "success",
            "session_id": session_id,
            "data": results,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/history")
async def get_chat_history(url: str, session_id: Optional[str] = None, x_session_id: Optional[str] = Header(None)):
    sid = x_session_id or session_id or "default_session"
    session_store = session_manager.get_session(sid)
    url_key = _cache_key(url)
    history = session_store.chat_histories.get(url_key, [])
    return {"status": "success", "session_id": sid, "url": url, "history": history}


@app.post("/api/chat/clear")
async def clear_chat_history(req: ClearChatRequest, x_session_id: Optional[str] = Header(None)):
    sid = x_session_id or req.session_id or "default_session"
    session_store = session_manager.get_session(sid)
    url_key = _cache_key(req.url)
    session_store.chat_histories[url_key] = []
    return {"status": "success", "session_id": sid, "url": req.url}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatStreamRequest, x_session_id: Optional[str] = Header(None)):
    """
    Server-Sent Events endpoint with session isolation and multi-source audit grounding.
    """
    if not req.url or not req.question.strip():
        raise HTTPException(status_code=400, detail="URL and question are required")

    sid = x_session_id or req.session_id or "default_session"
    session_store = session_manager.get_session(sid)
    url_key = _cache_key(req.url)

    crawl_data = session_store.crawls.get(url_key) or _crawl_cache.get(url_key)
    if not crawl_data:
        raise HTTPException(
            status_code=404,
            detail="No cached crawl data for this session. Please run an audit first.",
        )

    deep = req.deep or False
    top_n = 5 if deep else 3

    # Resolve conversation history for this session & url
    if req.conversation_history is not None:
        history = list(req.conversation_history)
    else:
        history = list(session_store.chat_histories.get(url_key, []))

    async def event_generator():
        loop = asyncio.get_event_loop()

        # 1. Multi-source Retrieval
        engine = GroundedQAEngine(crawl_data)
        audit_context = engine.get_audit_context()
        sources = await loop.run_in_executor(
            None, engine.get_passages, req.question, top_n, True, history
        )

        # 2. Stream tokens from Groq
        full_text = ""
        has_key   = llm_helper.has_key()

        import queue as _queue
        token_queue: _queue.Queue = _queue.Queue()
        SENTINEL = object()

        def _stream_worker():
            try:
                for token in llm_helper.stream_answer(
                    req.question, sources, history, deep=deep, audit_context=audit_context
                ):
                    token_queue.put(token)
            finally:
                token_queue.put(SENTINEL)

        stream_future = loop.run_in_executor(None, _stream_worker)

        while True:
            try:
                token = await loop.run_in_executor(None, token_queue.get, True, 30)
            except Exception:
                break
            if token is SENTINEL:
                break
            full_text += token
            yield f"data: {json.dumps({'token': token})}\n\n"

        await stream_future

        # Save turns into multi-tenant session history
        if url_key not in session_store.chat_histories:
            session_store.chat_histories[url_key] = []
        session_store.chat_histories[url_key].append({"role": "user", "content": req.question})
        session_store.chat_histories[url_key].append({"role": "assistant", "content": full_text})

        # 3. Final metadata event
        confidence = round(min(sources[0]["score"] / 10.0, 1.0), 2) if sources else 0.85
        payload = json.dumps({
            "done":       True,
            "sources":    sources[:3],
            "confidence": confidence,
            "has_key":    has_key,
            "answer":     full_text,
        })
        yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Static serving (AFTER all API routes) ─────────────────────────────────────
web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(web_dir, "index.html"))

@app.get("/{filename}")
async def serve_static(filename: str):
    fp = os.path.join(web_dir, filename)
    if os.path.isfile(fp):
        return FileResponse(fp)
    return FileResponse(os.path.join(web_dir, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

