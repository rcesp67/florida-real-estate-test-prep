#!/usr/bin/env python3
"""Chat-tutor backend for the Florida Real Estate Test Prep app. Stdlib only.

Routes:
  GET  /api/health -> {"ok": true}
  POST /api/chat   -> {"message": str, "history": [{role, content}]}
                      returns {"reply": str, "lesson": int|null, "lessonTitle": str|null}

Env:
  OPENAI_API_KEY  (required)
  ALLOWED_ORIGIN  (CORS origin, defaults to the production app)
  PORT            (Render injects this)
"""
import json
import os
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
ALLOWED_ORIGIN = os.environ.get(
    "ALLOWED_ORIGIN", "https://florida-real-estate-test-prep.onrender.com"
)
PORT = int(os.environ.get("PORT", "10000"))

LESSONS = [
    "The real estate business",
    "License law and qualifications",
    "FREC, DBPR, and discipline",
    "Brokerage relationships",
    "Brokerage activities and procedures",
    "Violations, penalties, and ethics",
    "Federal and state property laws",
    "Property rights, estates & co-ownership",
    "Title, deeds, and restrictions",
    "Legal descriptions",
    "Real estate contracts",
    "Residential mortgages",
    "Mortgage types and sources",
    "Real estate mathematics",
    "The real estate market",
    "Real estate appraisal",
    "Investment and business opportunity brokerage",
    "Taxes affecting real estate",
    "Planning, zoning, and the environment",
]

SYSTEM = (
    "You are a friendly tutor for the Florida Real Estate Sales Associate license exam. "
    "Answer the student's question concisely (a few sentences; longer only if they ask for detail). "
    "Base Florida-specific facts on standard exam material (Florida Statutes Chapter 475, FREC and DBPR rules). "
    "If you are unsure of a fact, say so instead of guessing.\n"
    "The course has 19 lessons:\n"
    + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(LESSONS))
    + '\nRespond ONLY with JSON: {"reply": "answer in plain text, no markdown", '
    '"lesson": <1-19 most relevant lesson number or null>, "lessonTitle": "<title or null>"}. '
    "Set lesson only when the question clearly relates to one lesson's topic."
)

# Simple per-IP rate limit: 30 requests/hour, to protect the owner's OpenAI bill.
_hits = {}


def allowed(ip):
    now = time.time()
    h = [t for t in _hits.get(ip, []) if now - t < 3600]
    if len(h) >= 30:
        return False
    h.append(now)
    _hits[ip] = h
    return True


def ask_openai(message, history):
    msgs = [{"role": "system", "content": SYSTEM}]
    for m in (history or [])[-6:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": str(m["content"])[:2000]})
    msgs.append({"role": "user", "content": message[:2000]})
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "max_tokens": 600,
            "temperature": 0.3,
            "messages": msgs,
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body, method="POST"
    )
    req.add_header("Authorization", "Bearer " + OPENAI_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        return json.loads(d["choices"][0]["message"]["content"])
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {str(e)[:200]}"}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            return self._json(404, {"error": "not found"})
        if not OPENAI_KEY:
            return self._json(500, {"error": "server misconfigured"})
        if not allowed(self.client_address[0]):
            return self._json(429, {"error": "too many requests, try again later"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad request"})
        message = str(data.get("message", "")).strip()
        if not message:
            return self._json(400, {"error": "empty message"})
        out = ask_openai(message, data.get("history"))
        if "_error" in out:
            return self._json(502, {"error": "tutor unavailable, try again"})
        reply = str(out.get("reply", "")).strip()
        if not reply:
            return self._json(502, {"error": "tutor unavailable, try again"})
        lesson = out.get("lesson")
        title = None
        if isinstance(lesson, int) and 1 <= lesson <= len(LESSONS):
            title = LESSONS[lesson - 1]
        else:
            lesson = None
        return self._json(200, {"reply": reply, "lesson": lesson, "lessonTitle": title})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
