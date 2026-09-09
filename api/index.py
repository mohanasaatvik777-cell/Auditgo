"""
Vercel ASGI entry point.
Vercel's @vercel/python runtime calls this module and looks for `app`.
We simply re-export the FastAPI app from server.py — Vercel wraps it in Mangum
automatically when it detects an ASGI app.
"""
import sys
import os

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app  # noqa: F401 — Vercel needs `app` in scope

# Vercel's Python runtime uses Mangum internally to adapt ASGI ↔ Lambda
# No extra code needed — just export `app`.
