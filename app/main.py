"""The API. Run it with:  python -m uvicorn app.main:app --reload
Then open http://localhost:8000/docs to try every endpoint in your browser."""
import logging
import time
import uuid

from fastapi import FastAPI, Request

from app import config, db, errors
from app.deps import get_services
from app.routes import compare, meta, products

log = logging.getLogger("skincare")
if not log.handlers:                      # show our own notes (like photo timings) in the API window
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False

app = FastAPI(title="Skincare and Haircare Comparison API", version=config.APP_VERSION)
errors.install(app)
app.include_router(meta.router)
app.include_router(products.router)
app.include_router(compare.router)


@app.middleware("http")
async def request_id_and_log(request: Request, call_next):
    request.state.request_id = "req_" + uuid.uuid4().hex[:10]
    request.state.error_code = ""
    request.state.log_extra = {}
    start = time.perf_counter()
    status = 502
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        request.state.error_code = "INTERNAL_ERROR"
        raise
    finally:
        if request.url.path.startswith("/v1/"):
            _log_request(request, status, start)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def _log_request(request: Request, status: int, start: float) -> None:
    """Saves counts and timings only. No ingredients, profiles or photos."""
    try:
        conn = db.connect()
        extra = request.state.log_extra
        conn.execute(
            "INSERT INTO request_log (request_id, timestamp, endpoint, status_code, error_code, product_type, "
            "n_products, n_unresolved, summary_source, latency_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (request.state.request_id, db.now_iso(), request.url.path, status, request.state.error_code,
             extra.get("product_type", ""), extra.get("n_products", 0), extra.get("n_unresolved", 0),
             extra.get("summary_source", ""), int((time.perf_counter() - start) * 1000)))
        conn.commit()
        conn.close()
    except Exception:
        log.exception("Could not write request log")   # logging must never break a request


@app.get("/health")
def health():
    """Says the service is running, and whether a Gemini key has been set (never shows the key)."""
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        "rules_loaded": len(get_services().data["rules"]),
        "llm_configured": bool(config.GEMINI_API_KEY),
    }
