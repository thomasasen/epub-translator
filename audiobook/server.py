"""Separate FastAPI-Weboberfläche hinter Nginx auf /audiobook/."""
from __future__ import annotations
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .core import safe_path
from .engine import MODEL_ID, VOICES
from .pipeline import (ROOT, TRANSLATED, STOP_EVENT, CANCEL_EVENT, ACTIVE_LOCK, approve, configure,
                       create_book, load, project_path, quality, synthesize, make_export, preview_term)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
CURRENT = None
HTML = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")


class ConfigRequest(BaseModel):
    settings: dict = {}
    glossary: dict | None = None


class RunRequest(BaseModel):
    preview: bool = False
    chapter: int | None = None
    force_id: str | None = None


def bad(exc):
    return HTTPException(400, str(exc))


@app.get("/audiobook/")
def home():
    return HTMLResponse(HTML, headers={"Cache-Control": "no-store"})


@app.get("/audiobook/health")
def health():
    return {"ok": True, "tts_busy": ACTIVE_LOCK.locked(), "model": MODEL_ID}


@app.get("/audiobook/api/books")
def books():
    ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for p in sorted(ROOT.iterdir()):
        if re.fullmatch("[a-f0-9]{12}", p.name) and (p / "manifest.json").is_file():
            try:
                state = load(p.name)
                results.append({"id": p.name, "title": state["title"], "status": state["status"]})
            except (ValueError, OSError, KeyError):
                pass
    return results


@app.get("/audiobook/api/translated")
def translated():
    if not TRANSLATED.is_dir():
        return []
    return [p.name for p in sorted(TRANSLATED.glob("*.epub"))
            if p.is_file() and p.resolve().parent == TRANSLATED.resolve()][:500]


@app.post("/audiobook/api/upload")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".epub"):
        raise HTTPException(400, "Nur EPUB-Dateien zulässig")
    ROOT.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(suffix=".epub", dir=ROOT)
    try:
        with os.fdopen(fd, "wb") as out:
            total = 0
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > 150 * 1024 * 1024:
                    raise HTTPException(413, "Datei größer als 150 MB")
                out.write(block)
        return {"id": create_book(Path(filename))}
    except (ValueError, OSError) as exc:
        raise bad(exc)
    finally:
        Path(filename).unlink(missing_ok=True)
        await file.close()


@app.post("/audiobook/api/import-translated")
async def from_translated(data: dict):
    try:
        name = data["name"]
        if not isinstance(name, str) or "/" in name or "\\" in name:
            raise ValueError("Ungültiger Dateiname")
        path = safe_path(TRANSLATED, name)
        if path.parent != TRANSLATED.resolve() or path.suffix.lower() != ".epub" or not path.is_file():
            raise ValueError("EPUB nicht gefunden")
        return {"id": create_book(path)}
    except (KeyError, ValueError, OSError) as exc:
        raise bad(exc)


@app.get("/audiobook/api/books/{book_id}")
def book(book_id: str):
    try:
        return load(book_id)
    except (ValueError, OSError) as exc:
        raise bad(exc)


@app.put("/audiobook/api/books/{book_id}/config")
def config(book_id: str, data: ConfigRequest):
    if ACTIVE_LOCK.locked():
        raise HTTPException(409, "Ein Job läuft bereits")
    try:
        return configure(book_id, data.settings, data.glossary)
    except (ValueError, OSError) as exc:
        raise bad(exc)


@app.post("/audiobook/api/books/{book_id}/approve")
def allow(book_id: str):
    try:
        return approve(book_id)
    except (ValueError, OSError) as exc:
        raise bad(exc)


@app.post("/audiobook/api/books/{book_id}/run")
def run(book_id: str, data: RunRequest):
    global CURRENT
    if CURRENT is not None and CURRENT.is_alive():
        raise HTTPException(409, "Ein anderer Job läuft bereits")
    try:
        load(book_id)
        if data.force_id and not re.fullmatch(r"\d{4}-\d{5}", data.force_id):
            raise ValueError("Ungültige Segment-ID")
    except (ValueError, OSError) as exc:
        raise bad(exc)
    def job():
        try:
            synthesize(book_id, preview=data.preview, chapter=data.chapter, force_id=data.force_id)
        except Exception as exc:
            print("Audiobook job: " + str(exc), flush=True)
    CURRENT = threading.Thread(target=job, daemon=True)
    CURRENT.start()
    return {"accepted": True}


@app.post("/audiobook/api/books/{book_id}/pause")
def pause(book_id: str):
    try:
        load(book_id)
    except (ValueError, OSError) as exc:
        raise bad(exc)
    STOP_EVENT.set()
    return {"pause_requested": True}


@app.post("/audiobook/api/books/{book_id}/cancel")
def cancel(book_id: str):
    try:
        load(book_id)
    except (ValueError, OSError) as exc:
        raise bad(exc)
    CANCEL_EVENT.set()
    STOP_EVENT.set()
    return {"cancel_requested": True, "note": "Bereits generierte Segmente bleiben vorhanden"}


@app.post("/audiobook/api/books/{book_id}/export")
def export(book_id: str):
    if not ACTIVE_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Sprachgenerierung aktiv")
    try:
        make_export(book_id)
        state = load(book_id)
        state["status"] = "completed"
        from .pipeline import save
        save(book_id, state)
        return {"ready": True}
    except (ValueError, RuntimeError, OSError) as exc:
        raise bad(exc)
    finally:
        ACTIVE_LOCK.release()

@app.post("/audiobook/api/books/{book_id}/term-preview")
def term_preview(book_id: str, request: dict):
    try:
        token = preview_term(book_id, request.get("phrase", ""))
        return {"token": token}
    except (ValueError, OSError, RuntimeError) as exc:
        raise bad(exc)

@app.get("/audiobook/api/books/{book_id}/quality")
def report(book_id: str):
    try:
        return quality(book_id)
    except (ValueError, OSError) as exc:
        raise bad(exc)


@app.get("/audiobook/api/books/{book_id}/download/{kind}")
def download(book_id: str, kind: str, chapter: int | None = None, token: str | None = None):
    try:
        folder = project_path(book_id)
        if kind == "m4b":
            path = folder / "book.m4b"
        elif kind == "preview":
            path = folder / "preview.mp3"
        elif kind == "term" and token is not None and re.fullmatch(r"[a-f0-9]{16}", token):
            path = safe_path(folder, f"terms/{token}.mp3")
        elif kind == "quality":
            path = folder / "quality.json"
            if not path.is_file():
                quality(book_id)
        elif kind == "chapter" and chapter is not None and 1 <= chapter <= 10000:
            path = safe_path(folder, f"chapters/{chapter:04d}.mp3")
        else:
            raise ValueError("Unbekanntes Format")
        if not path.is_file():
            raise ValueError("Datei nicht vorhanden")
        return FileResponse(path, filename=path.name)
    except (ValueError, OSError) as exc:
        raise bad(exc)


@app.get("/audiobook/api/capabilities")
def capabilities():
    return {"engines": [{"id": "qwen-customvoice", "model": MODEL_ID}],
            "voices": VOICES}
