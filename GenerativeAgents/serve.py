"""Local server for placelab: serves the page and lets the agents talk through Gemini.

    python serve.py              # then open http://127.0.0.1:8000
    python serve.py --port 8001

Reads GEMINI_API_KEY (and optionally GEMINI_MODEL) from GenerativeAgents/.env or the environment.
The key never reaches the browser: the page sends each conversation's context here, this server
adds the prompt from prompts/, calls Gemini, checks the answer against a fixed shape and returns it.
Without a key the page still runs, with the offline conversations of src/offline.js (fixed rules, no AI).

It also keeps the agents' episodic memory and finished runs in data/ (git-ignored, plain JSON):
    data/episodes.jsonl   one line per conversation, read back as memories in later runs
    data/runs/run-N.json  each finished run: transcript, ideas, newsletter, chart data
Only src/ and visual-summary/ are served as files; .env, data/ and the rest of the folder are not.
Standard library only.
"""
import argparse, json, os, pathlib, re, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.environ.get("PLACELAB_DATA") or ROOT / "data")   # override for tests
EPISODES = DATA / "episodes.jsonl"
RUNS = DATA / "runs"
PROMPTS = ROOT / "prompts"
SERVED = ("src", "visual-summary")          # the only folders served as files
MAX_BODY = 4_000_000                         # a finished run with its chart data is well under this
MAX_EPISODES_READ = 400                      # most recent memories handed back to the page


def load_env(path):
    """KEY=VALUE lines; the real environment wins over the file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(ROOT / ".env")
KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# Flash-Lite answers a conversation in about 1.5 s; Flash thinks first and takes 25-50 s (measured 2026-11-09)
MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-flash-lite-latest"
BASE = os.environ.get("GEMINI_BASE_URL", "").strip().rstrip("/") or "https://generativelanguage.googleapis.com"
TIMEOUT = 90
GATE = threading.Semaphore(2)               # at most two model calls at once (free-tier rate limits)
LOCK = threading.Lock()                     # serialises writes to data/


# ---------- Gemini ----------
class LLMError(Exception):
    pass


def gemini(system, user, schema, temperature=1.0):
    """One generateContent call with structured JSON output. Retries rate limits and overload."""
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 8192,
                                 "responseMimeType": "application/json", "responseSchema": schema}}
    url = f"{BASE}/v1beta/models/{MODEL}:generateContent"
    req = lambda: urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
    with GATE:
        for attempt in range(4):
            t0 = time.time()
            try:
                with urllib.request.urlopen(req(), timeout=TIMEOUT) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:400]
                if e.code in (429, 500, 503) and attempt < 3:
                    m = re.search(r'"retryDelay":\s*"(\d+)', detail)
                    wait = min(30, int(m.group(1)) if m else 2 * 3 ** attempt)
                    print(f"  gemini {e.code}, retrying in {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                raise LLMError(f"Gemini returned {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError) as e:
                raise LLMError(f"Could not reach Gemini: {e}")
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    use = data.get("usageMetadata", {})
    print(f"  gemini {MODEL}: {time.time() - t0:.1f}s, {use.get('promptTokenCount', '?')} in / "
          f"{use.get('candidatesTokenCount', '?')} out, {cand.get('finishReason', '?')}", flush=True)
    if not text:
        raise LLMError(f"Gemini returned no text (finish reason {cand.get('finishReason')}, "
                       f"block {data.get('promptFeedback', {}).get('blockReason')})")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise LLMError("Gemini's answer was not valid JSON")


def prompt(name, **values):
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def clip(v, n):
    return v.strip()[:n] if isinstance(v, str) else ""


LANGS = {"en": "English", "es": "Spanish"}

# ---------- conversation ----------
S, A_, O = "STRING", "ARRAY", "OBJECT"
CONVERSE_SCHEMA = {"type": O, "properties": {
    "lines": {"type": A_, "items": {"type": O, "properties": {
        "speaker": {"type": S, "enum": ["A", "B"]}, "text": {"type": S}}, "required": ["speaker", "text"]}},
    "insight": {"type": S},
    "outcome": {"type": S, "enum": ["new_idea", "build_on", "none"]},
    "idea_title": {"type": S}, "idea_pitch": {"type": S}, "builds_on": {"type": S}},
    "required": ["lines", "insight", "outcome"]}


def converse(ctx):
    """ctx comes from the page: place, time, both agents' chosen topic and memories, ideas in play."""
    ideas = {clip(i.get("id"), 40) for i in ctx.get("ideas", []) if isinstance(i, dict)}
    system = prompt("converse", language=LANGS.get(ctx.get("lang"), "English"))
    out = gemini(system, json.dumps(ctx, ensure_ascii=False, indent=1), CONVERSE_SCHEMA)
    lines = [{"speaker": l.get("speaker"), "text": clip(l.get("text"), 400)} for l in out.get("lines", [])
             if isinstance(l, dict) and l.get("speaker") in ("A", "B") and clip(l.get("text"), 400)][:10]
    if len(lines) < 2:
        raise LLMError("Gemini's conversation had fewer than two lines")
    outcome, title, pitch = out.get("outcome"), clip(out.get("idea_title"), 90), clip(out.get("idea_pitch"), 500)
    builds_on = clip(out.get("builds_on"), 40)
    if outcome == "build_on" and builds_on not in ideas:   # only ideas the page offered can be built on
        outcome, builds_on = ("new_idea" if title else "none"), ""
    if outcome in ("new_idea", "build_on") and not (title and pitch):
        outcome = "none"
    return {"lines": lines, "insight": clip(out.get("insight"), 400) or "",
            "outcome": outcome if outcome in ("new_idea", "build_on", "none") else "none",
            "idea_title": title if outcome != "none" else "", "idea_pitch": pitch if outcome != "none" else "",
            "builds_on": builds_on if outcome == "build_on" else ""}


NEWSLETTER_SCHEMA = {"type": O, "properties": {
    "headline": {"type": S}, "lede": {"type": S},
    "stories": {"type": A_, "items": {"type": O, "properties": {
        "idea_id": {"type": S}, "headline": {"type": S}, "blurb": {"type": S}}, "required": ["idea_id", "headline", "blurb"]}},
    "column_title": {"type": S}, "column": {"type": S}},
    "required": ["headline", "lede", "stories", "column_title", "column"]}


def newsletter(ctx):
    ideas = {clip(i.get("id"), 40) for i in ctx.get("ideas", []) if isinstance(i, dict)}
    system = prompt("newsletter", language=LANGS.get(ctx.get("lang"), "English"))
    out = gemini(system, json.dumps(ctx, ensure_ascii=False, indent=1), NEWSLETTER_SCHEMA, temperature=0.8)
    stories = [{"idea_id": clip(s.get("idea_id"), 40), "headline": clip(s.get("headline"), 120), "blurb": clip(s.get("blurb"), 700)}
               for s in out.get("stories", []) if isinstance(s, dict) and clip(s.get("idea_id"), 40) in ideas][:12]
    return {"headline": clip(out.get("headline"), 120), "lede": clip(out.get("lede"), 700), "stories": stories,
            "column_title": clip(out.get("column_title"), 100), "column": clip(out.get("column"), 1500)}


# ---------- memory and runs ----------
def read_episodes():
    if not EPISODES.exists():
        return []
    out = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out[-MAX_EPISODES_READ:]


def valid_episode(e):
    return (isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("a"), str) and isinstance(e.get("b"), str)
            and isinstance(e.get("run"), int) and isinstance(e.get("insight", ""), str) and len(json.dumps(e)) <= 4000)


def run_ids():
    return sorted((int(p.stem[4:]) for p in RUNS.glob("run-*.json") if p.stem[4:].isdigit()))


# ---------- HTTP ----------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            super().log_message(fmt, *args)

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(b)
        except ConnectionError:   # the page was closed or reloaded before the answer arrived
            pass

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    # files: only src/ and visual-summary/, no directory listings
    def translate_path(self, path):
        p = super().translate_path(path)
        rel = pathlib.Path(p).resolve()
        if not any(rel == ROOT / d or (ROOT / d) in rel.parents for d in SERVED):
            return str(ROOT / "__not_served__")
        return str(rel)

    def list_directory(self, path):
        self.send_error(404)

    def end_headers(self):
        if not (self.path or "").startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        if self.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/src/")
            self.end_headers()
            return
        if self.path == "/api/status":
            return self.send_json({"llm": bool(KEY), "model": MODEL if KEY else None,
                                   "episodes": len(read_episodes()), "runs": len(run_ids())})
        if self.path == "/api/episodes":
            return self.send_json({"episodes": read_episodes()})
        if self.path == "/api/runs":
            out = []
            for n in run_ids():
                try:
                    r = json.loads((RUNS / f"run-{n}.json").read_text(encoding="utf-8"))
                    out.append({"id": r.get("id"), "n": n, "created": r.get("created"), "stats": r.get("stats")})
                except (OSError, json.JSONDecodeError):
                    pass
            return self.send_json({"runs": out})
        m = re.fullmatch(r"/api/runs/run-(\d+)", self.path)
        if m:
            f = RUNS / f"run-{m.group(1)}.json"
            return self.send_json(json.loads(f.read_text(encoding="utf-8"))) if f.exists() else self.send_json({"error": "no such run"}, 404)
        if self.path.startswith("/api/"):
            return self.send_json({"error": "unknown endpoint"}, 404)
        super().do_GET()

    def do_POST(self):
        try:
            if self.path in ("/api/converse", "/api/newsletter"):
                if not KEY:
                    return self.send_json({"error": "no GEMINI_API_KEY in .env"}, 503)
                ctx = self.body()
                return self.send_json((converse if self.path == "/api/converse" else newsletter)(ctx))
            if self.path == "/api/episodes":
                eps = [e for e in self.body().get("episodes", [])[:50] if valid_episode(e)]
                with LOCK:
                    DATA.mkdir(exist_ok=True)
                    with EPISODES.open("a", encoding="utf-8") as f:
                        for e in eps:
                            f.write(json.dumps(e, ensure_ascii=False) + "\n")
                return self.send_json({"saved": len(eps)})
            if self.path == "/api/runs":
                rec = self.body()
                if not isinstance(rec, dict) or not isinstance(rec.get("chart"), dict):
                    return self.send_json({"error": "expected a run record"}, 400)
                with LOCK:
                    RUNS.mkdir(parents=True, exist_ok=True)
                    n = (run_ids() or [0])[-1] + 1
                    rec["id"] = f"run-{n}"
                    (RUNS / f"run-{n}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                return self.send_json({"id": rec["id"], "n": n})
            self.send_json({"error": "unknown endpoint"}, 404)
        except LLMError as e:
            print(f"  {e}", flush=True)
            self.send_json({"error": str(e)}, 502)
        except (ValueError, json.JSONDecodeError) as e:
            self.send_json({"error": f"bad request: {e}"}, 400)

    def do_DELETE(self):
        if self.path == "/api/episodes":          # "forget earlier runs" in the page
            with LOCK:
                if EPISODES.exists():
                    EPISODES.replace(DATA / f"episodes-forgotten-{int(time.time())}.jsonl")
            return self.send_json({"forgotten": True})
        self.send_json({"error": "unknown endpoint"}, 404)


def check_model():
    try:
        r = urllib.request.Request(f"{BASE}/v1beta/models/{MODEL}", headers={"x-goog-api-key": KEY})
        with urllib.request.urlopen(r, timeout=15) as resp:
            info = json.loads(resp.read())
        print(f"Gemini: {MODEL} ({info.get('displayName', '')})")
    except urllib.error.HTTPError as e:
        print(f"Gemini: could not use model {MODEL!r} ({e.code}). Set GEMINI_MODEL in .env; Flash models for this key:")
        try:
            r = urllib.request.Request(f"{BASE}/v1beta/models?pageSize=200", headers={"x-goog-api-key": KEY})
            with urllib.request.urlopen(r, timeout=15) as resp:
                names = [m["name"].split("/")[-1] for m in json.loads(resp.read()).get("models", [])
                         if "flash" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", [])]
            print("  " + ", ".join(names))
        except Exception:
            pass
    except Exception as e:
        print(f"Gemini: could not reach the API to check the model ({e}); conversations will retry per request.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    gen = subprocess.run([sys.executable, str(ROOT / "tools" / "roster2profiles.py")], capture_output=True, text=True, encoding="utf-8")
    print((gen.stdout or gen.stderr).strip() or "profiles regenerated")
    if gen.returncode:
        print("Serving the previous src/profiles.js until people/ is fixed.")
    if KEY:
        check_model()
    else:
        print("No GEMINI_API_KEY in .env: agents will talk by fixed rules, without AI (src/offline.js). See .env.example.")
    # on Windows, SO_REUSEADDR lets a second server silently share a busy port; fail clearly instead
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        sys.exit(f"Port {args.port} is already in use. Stop the other server, or run: python serve.py --port {args.port + 1}")
    print(f"placelab on http://127.0.0.1:{args.port}  (Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
