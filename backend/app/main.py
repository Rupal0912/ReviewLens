"""FastAPI app. The browser only talks to these endpoints; it never sees the LLM or its key."""
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .analysis import generate_reply, process_upload
from .cleaning import CSVError
from .dashboard import build_dashboard
from .db import Database
from .llm import GroqClient, LLMConfigError, LLMError

app = FastAPI(title="ReviewLens API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# Created lazily so tests can swap them: app.state.db / app.state.llm
app.state.db = None
app.state.llm = None


def get_db() -> Database:
    if app.state.db is None:
        app.state.db = Database(config.DB_PATH)
    return app.state.db


def get_llm():
    if app.state.llm is None:
        app.state.llm = GroqClient()
    return app.state.llm


def _dashboard(upload_id: int) -> dict:
    db = get_db()
    upload = db.get_upload(upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    return build_dashboard(upload, db.get_reviews(upload_id))


@app.get("/api/health")
def health():
    return {"ok": True, "llm_configured": bool(config.GROQ_API_KEY)}


@app.post("/api/upload")
def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file.")
    content = file.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 2 MB.")
    try:
        upload_id = process_upload(get_db(), get_llm(), file.filename, content)
    except CSVError as exc:
        raise HTTPException(400, str(exc))
    except LLMConfigError as exc:
        raise HTTPException(503, str(exc))
    return _dashboard(upload_id)


@app.get("/api/dashboard/latest")
def latest():
    upload_id = get_db().latest_upload_id()
    if upload_id is None:
        raise HTTPException(404, "No uploads yet")
    return _dashboard(upload_id)


@app.get("/api/dashboard/{upload_id}")
def dashboard(upload_id: int):
    return _dashboard(upload_id)


@app.post("/api/reviews/{row_id}/reply")
def suggest_reply(row_id: int):
    """Only called when the user clicks 'Suggest reply'. Result is stored so a click is never repeated."""
    db = get_db()
    review = db.get_review(row_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if review["status"] != "analyzed" or not review["needs_reply"]:
        raise HTTPException(400, "This review does not need a reply.")
    if review["suggested_reply"]:
        return {"suggested_reply": review["suggested_reply"], "cached": True}
    try:
        reply = generate_reply(get_llm(), review)
    except LLMConfigError as exc:
        raise HTTPException(503, str(exc))
    except LLMError as exc:
        raise HTTPException(502, f"Could not generate a reply: {exc}")
    db.save_reply(row_id, reply)
    return {"suggested_reply": reply, "cached": False}
