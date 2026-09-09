import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
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

# ── In-memory crawl session cache ─────────────────────────────────────────────
_crawl_cache: Dict[str, dict] = {}
MAX_CACHE = 5

def _cache_key(url: str) -> str:
    return url.strip().rstrip("/").lower()

def _store_crawl(url: str, crawl_data: dict):
    key = _cache_key(url)
    _crawl_cache[key] = crawl_data
    if len(_crawl_cache) > MAX_CACHE:
        del _crawl_cache[next(iter(_crawl_cache))]

def _get_crawl(url: str) -> Optional[dict]:
    return _crawl_cache.get(_cache_key(url))


# ── Models ─────────────────────────────────────────────────────────────────────

class AuditRequest(BaseModel):
    url: str
    query: Optional[str] = None
    output_dir: Optional[str] = "outputs"
    groq_api_key: Optional[str] = None

class ChatStreamRequest(BaseModel):
    url: str
    question: str
    conversation_history: Optional[List[Dict]] = []
    groq_api_key: Optional[str] = None
    deep: Optional[bool] = False           # True = deep analysis mode


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status":   "ok",
        "app":      "Auditgo",
        "groq_key": llm_helper.has_key(),
    }


@app.post("/api/audit")
async def execute_audit(req: AuditRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Target URL is required")

    if req.groq_api_key and req.groq_api_key.strip():
        llm_helper.set_api_key(req.groq_api_key.strip())

    try:
        loop    = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, run_agent,
            req.url.strip(), req.query,
            req.output_dir or "outputs", [],
        )
        crawl_data = results.pop("_crawl_data", None)
        if crawl_data:
            _store_crawl(req.url.strip(), crawl_data)

        return JSONResponse(content={"status": "success", "data": results})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    """
    Server-Sent Events endpoint.

    Quick mode (deep=False): llama-3.1-8b-instant, top-2 passages, ~1-3s.
    Deep  mode (deep=True):  llama-3.3-70b-versatile, top-5 passages, ~5-10s.

    Stream format:
        data: {"token": "..."}          — partial token
        data: {"done": true, "sources": [...], "confidence": 0.x, "has_key": bool}
    """
    if not req.url or not req.question.strip():
        raise HTTPException(status_code=400, detail="URL and question are required")

    # Always honour key sent from browser
    if req.groq_api_key and req.groq_api_key.strip():
        llm_helper.set_api_key(req.groq_api_key.strip())

    crawl_data = _get_crawl(req.url.strip())
    if not crawl_data:
        raise HTTPException(
            status_code=404,
            detail="No cached crawl data. Please run a full audit first.",
        )

    deep   = req.deep or False
    top_n  = 5 if deep else 2
    history = req.conversation_history or []

    async def event_generator():
        loop = asyncio.get_event_loop()

        # ── 1. BM25 retrieval (fast, in thread pool) ──────────
        engine  = GroundedQAEngine(crawl_data)
        sources = await loop.run_in_executor(
            None, engine.get_passages, req.question, top_n
        )

        if not sources:
            payload = json.dumps({
                "done":       True,
                "sources":    [],
                "confidence": 0.0,
                "has_key":    llm_helper.has_key(),
                "answer":     (
                    f'No relevant content found for "{req.question}". '
                    "Try rephrasing or asking a different question."
                ),
            })
            yield f"data: {payload}\n\n"
            return

        # ── 2. Stream tokens from Groq ─────────────────────────
        full_text = ""
        has_key   = llm_helper.has_key()

        # run_in_executor can't yield — so we stream directly in a thread
        # via a queue bridging sync generator → async generator
        import queue as _queue
        token_queue: _queue.Queue = _queue.Queue()
        SENTINEL = object()

        def _stream_worker():
            try:
                for token in llm_helper.stream_answer(
                    req.question, sources, history, deep=deep
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

        await stream_future  # ensure thread finishes

        # ── 3. Send final metadata event ──────────────────────
        confidence = round(min(sources[0]["score"] / 10.0, 1.0), 2) if sources else 0.0
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
