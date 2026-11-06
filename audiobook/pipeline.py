"""Persistente Hörbuch-Jobs, explizite Preview-Freigabe und FFmpeg-Mastering."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .core import atomic_json, checksum, load_glossary, read_epub, safe_path, segments
from .engine import MODEL_ID, create_engine, inspect_wav

ROOT = Path(os.getenv("AUDIOBOOK_ROOT", "/workspace/epub-translator/audiobooks"))
TRANSLATED = Path(os.getenv("AUDIOBOOK_TRANSLATED", "/workspace/epub-translator/translated_files"))
ACTIVE_LOCK = threading.Lock()
STOP_EVENT = threading.Event()
CANCEL_EVENT = threading.Event()
SETTINGS = {
    "backend": "qwen-customvoice", "speaker": "Ryan", "instruction":
    "Speak in clear, measured German. Calm, professional non-fiction narration. "
    "Natural punctuation pauses, no dramatic emphasis.",
    "speed": 1.0, "max_chars": 400, "seed": 1106,
    "captions": False, "notes": False, "quality": "high",
}
ID = re.compile(r"^[a-f0-9]{12}$")


def project_path(book_id: str) -> Path:
    if not ID.fullmatch(book_id):
        raise ValueError("Ungültige Buch-ID")
    return safe_path(ROOT, book_id)


def load(book_id: str) -> dict:
    return json.loads((project_path(book_id) / "manifest.json").read_text(encoding="utf-8"))


def save(book_id: str, state: dict) -> None:
    state["updated_at"] = int(time.time())
    atomic_json(project_path(book_id) / "manifest.json", state)


def _build_segments(chapters: list, glossary: dict, cfg: dict) -> list:
    result = []
    for chapter in chapters:
        parts = segments(chapter["blocks"], glossary, cfg["max_chars"])
        for index, part in enumerate(parts, 1):
            record = dict(part)
            record.update({"id": f"{chapter['id']:04d}-{index:05d}",
                           "chapter": chapter["id"], "index": index})
            result.append(record)
    return result


def _fingerprint(cfg: dict, glossary: dict) -> str:
    return checksum(json.dumps([cfg, glossary], ensure_ascii=False, sort_keys=True))


def create_book(source: Path, *, config: dict | None = None) -> str:
    """Import only data bytes; never trust filenames or paths as output names."""
    from secrets import token_hex
    ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(source)
    data_hash = checksum(path.read_bytes())
    cfg = dict(SETTINGS)
    if config:
        cfg = checked_config(config)
    book_id = token_hex(6)
    folder = project_path(book_id)
    folder.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copyfile(path, folder / "source.epub")
        parsed = read_epub(folder / "source.epub", captions=cfg["captions"], notes=cfg["notes"])
        glossary = load_glossary()
        parts = _build_segments(parsed["chapters"], glossary, cfg)
        state = {"id": book_id, "source_sha256": data_hash,
                 "title": parsed["metadata"]["title"], "author": parsed["metadata"]["author"],
                 "cover_path": parsed["metadata"]["cover"],
                 "chapters": [{"id": c["id"], "title": c["title"],
                               "characters": c["characters"]} for c in parsed["chapters"]],
                 "exclusions": parsed["exclusions"], "segments": parts,
                 "config": cfg, "glossary": glossary, "configuration_sha256": _fingerprint(cfg, glossary),
                 "approved_fingerprint": None, "status": "prepared", "errors": [],
                 "estimated_minutes": round(sum(c["characters"] for c in parsed["chapters"]) / 900, 1),
                 "updated_at": int(time.time())}
        save(book_id, state)
        return book_id
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def checked_config(new: dict) -> dict:
    cfg = dict(SETTINGS)
    if set(new) - set(cfg):
        raise ValueError("Unbekannte Konfigurationsparameter")
    cfg.update(new)
    if cfg["quality"] not in ("high", "careful"):
        raise ValueError("Unbekanntes Qualitätsprofil")
    if cfg["backend"] not in ("qwen-customvoice", "mock"):
        raise ValueError("Unbekanntes Modell")
    if cfg["backend"] == "mock" and os.getenv("AUDIOBOOK_TEST_MOCK") != "1":
        raise ValueError("Mock-Engine ist nur für isolierte Tests erlaubt")
    from .engine import VOICES
    if cfg["backend"] != "mock" and cfg["speaker"] not in VOICES:
        raise ValueError("Unbekannte Stimme")
    if not (0.8 <= float(cfg["speed"]) <= 1.2):
        raise ValueError("Geschwindigkeit 0,8..1,2")
    if not (120 <= int(cfg["max_chars"]) <= 1200):
        raise ValueError("Segmentlänge 120..1200")
    if len(cfg["instruction"]) > 500 or not isinstance(cfg["seed"], int):
        raise ValueError("Ungültige Sprachparameter")
    cfg["captions"] = bool(cfg["captions"])
    cfg["notes"] = bool(cfg["notes"])
    return cfg


def configure(book_id: str, values: dict | None = None, glossary: dict | None = None) -> dict:
    state = load(book_id)
    cfg = checked_config({**state["config"], **(values or {})})
    words = state["glossary"] if glossary is None else glossary
    if not isinstance(words, dict) or len(words) > 500 or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in words.items()):
        raise ValueError("Ungültiges Ausspracheglossar")
    # Validate each entry against the same rules as the synthesis path.
    from .core import apply_glossary
    apply_glossary("Kontrolle", words)
    parsed = read_epub(project_path(book_id) / "source.epub",
                       captions=cfg["captions"], notes=cfg["notes"])
    fp = _fingerprint(cfg, words)
    if fp != state["configuration_sha256"]:
        state["approved_fingerprint"] = None
        state["status"] = "prepared"
    state.update({"config": cfg, "glossary": words, "configuration_sha256": fp,
                  "exclusions": parsed["exclusions"],
                  "segments": _build_segments(parsed["chapters"], words, cfg)})
    save(book_id, state)
    return state


def _wanted_preview(state: dict) -> list:
    """Drei unterschiedliche Textgruppen, bei kurzen Büchern entsprechend weniger."""
    all_parts = state["segments"]
    if not all_parts:
        return []
    sets = [[], [], []]
    terms = ("SaaS", "CRM", "Pipeline", "Forecast", "MEDDPICC", "Customer", "Sales", "Cloud")
    for item in all_parts:
        score = 2 if re.search(r"\d|[%€$]", item["text"]) else (1 if any(
            t.lower() in item["text"].lower() for t in terms) else 0)
        sets[score].append(item)
    sample = []
    # Up to approx 5-10 minutes for sufficiently long EPUBs; preserve source order.
    for group in sets:
        sample.extend(group[:5])
    unique = {s["id"]: s for s in sample}
    if len(unique) < 3:
        unique.update({x["id"]: x for x in all_parts[:3]})
    return sorted(unique.values(), key=lambda s: (s["chapter"], s["index"]))


def _signature(state: dict, item: dict) -> str:
    return checksum(json.dumps([item["text"], item["kind"], state["configuration_sha256"],
                                MODEL_ID if state["config"]["backend"] == "qwen-customvoice" else "mock-ci"],
                               ensure_ascii=False, sort_keys=True))


def _file(book_id: str, item: dict, signature: str) -> Path:
    return safe_path(project_path(book_id), f"segments/{item['id']}-{signature[:16]}.wav")


def _run(args: list[str], *, timeout: int = 7200) -> None:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if p.returncode:
        raise RuntimeError("FFmpeg-Fehler: " + p.stderr[-1200:])


def _ffconcat(paths: list[Path], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    listfile = destination.with_suffix(".concat.txt")
    listfile.write_text("\n".join(
        "file '" + str(p.resolve()).replace("'", "'\\''") + "'" for p in paths) + "\n",
        encoding="utf-8")
    return listfile


def _preview_file(book_id: str, paths: list[Path], cfg: dict) -> None:
    out = project_path(book_id) / "preview.mp3"
    lst = _ffconcat(paths, out)
    part = out.with_suffix(".part.mp3")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
          "-safe", "0", "-i", str(lst), "-filter:a", f"atempo={cfg['speed']},loudnorm=I=-19:TP=-2:LRA=11",
          "-c:a", "libmp3lame", "-b:a", "128k", str(part)])
    part.replace(out)


def synthesize(book_id: str, *, preview: bool = False, chapter: int | None = None,
               force_id: str | None = None) -> dict:
    if not ACTIVE_LOCK.acquire(blocking=False):
        raise RuntimeError("Bereits ein anderer TTS-Auftrag aktiv")
    STOP_EVENT.clear()
    CANCEL_EVENT.clear()
    engine = None
    state = load(book_id)
    try:
        if not preview and state["approved_fingerprint"] != state["configuration_sha256"]:
            raise ValueError("Vollproduktion erst nach ausdrücklicher Freigabe der aktuellen Sprachprobe")
        all_parts = state["segments"]
        chosen = _wanted_preview(state) if preview else all_parts
        if chapter is not None:
            chosen = [s for s in chosen if s["chapter"] == chapter]
        if force_id is not None:
            chosen = [s for s in all_parts if s["id"] == force_id]
            if not chosen:
                raise ValueError("Segment nicht vorhanden")
        if not chosen:
            raise ValueError("Keine Segmente für die gewählte Auswahl")
        state["status"] = "preview_running" if preview else "running"
        state["errors"] = []
        state["done"] = 0
        state["total"] = len(chosen)
        save(book_id, state)
        paths = []
        for item in chosen:
            if STOP_EVENT.is_set():
                state["status"] = "cancelled" if CANCEL_EVENT.is_set() else "paused"
                save(book_id, state)
                return state
            sig = _signature(state, item)
            path = _file(book_id, item, sig)
            healthy = False
            if path.exists():
                try:
                    healthy = inspect_wav(path)["seconds"] >= .25
                except (OSError, ValueError, EOFError):
                    pass
            if not healthy:
                if engine is None:
                    engine = create_engine(state["config"]["backend"])
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.stem + ".tmp.wav")
                try:
                    engine.synthesize(item["text"], temp,
                                      speaker=state["config"]["speaker"],
                                      instruction=state["config"]["instruction"],
                                      seed=state["config"]["seed"])
                    metrics = inspect_wav(temp)
                    if metrics["seconds"] < .25 or metrics["peak_clipped_share"] > .05:
                        raise RuntimeError("Segment-Audio unplausibel oder übersteuert")
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
            paths.append(path)
            state["done"] += 1
            save(book_id, state)
        if engine:
            engine.close()
            engine = None
        if STOP_EVENT.is_set():
            state["status"] = "cancelled" if CANCEL_EVENT.is_set() else "paused"
            save(book_id, state)
            return state
        if preview:
            _preview_file(book_id, paths, state["config"])
            state["status"] = "preview_ready"
        elif chapter is None and force_id is None:
            make_export(book_id)
            state["status"] = "completed"
        else:
            # Existing M4B is now stale after an individual segment change.
            if force_id is not None:
                (project_path(book_id) / "book.m4b").unlink(missing_ok=True)
            state["status"] = "partial_ready"
        save(book_id, state)
        return state
    except BaseException as exc:
        state["status"] = "failed"
        state.setdefault("errors", []).append(str(exc))
        save(book_id, state)
        raise
    finally:
        if engine:
            engine.close()
        ACTIVE_LOCK.release()


def approve(book_id: str) -> dict:
    state = load(book_id)
    if state["status"] != "preview_ready" or not (project_path(book_id) / "preview.mp3").is_file():
        raise ValueError("Zuerst Sprachprobe vollständig erzeugen und anhören")
    state["approved_fingerprint"] = state["configuration_sha256"]
    state["status"] = "approved"
    save(book_id, state)
    return state


def _ffmetadata(state: dict, durations: list[float], filename: Path) -> None:
    def clean(s):
        return str(s).replace("\\", "\\\\").replace("\n", " ").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")
    lines = [";FFMETADATA1", "title=" + clean(state["title"]), "artist=" + clean(state["author"])]
    start = 0
    for ch, duration in zip(state["chapters"], durations):
        end = start + round(duration * 1000)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}",
                  "title=" + clean(ch["title"])]
        start = end
    filename.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_export(book_id: str) -> Path:
    state = load(book_id)
    if state["approved_fingerprint"] != state["configuration_sha256"]:
        raise ValueError("Sprachprobe nicht freigegeben")
    folder = project_path(book_id)
    chapter_wavs, durations = [], []
    for ch in state["chapters"]:
        items = [s for s in state["segments"] if s["chapter"] == ch["id"]]
        if not items:
            raise RuntimeError("Leeres Kapitel, Vollständigkeit nicht gegeben")
        parts = [_file(book_id, s, _signature(state, s)) for s in items]
        for part in parts:
            if not part.exists():
                raise RuntimeError("Fehlendes Segment: " + part.name)
            inspect_wav(part)
        chapter_wav = folder / "chapters" / f"{ch['id']:04d}.wav"
        concatfile = _ffconcat(parts, chapter_wav)
        temp = chapter_wav.with_suffix(".part.wav")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
              "-safe", "0", "-i", str(concatfile), "-c:a", "pcm_s16le", str(temp)])
        temp.replace(chapter_wav)
        metrics = inspect_wav(chapter_wav)
        durations.append(metrics["seconds"] / state["config"]["speed"])
        chapter_wavs.append(chapter_wav)
        mp3 = chapter_wav.with_suffix(".mp3")
        mp3_temp = chapter_wav.with_suffix(".part.mp3")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(chapter_wav),
              "-af", f"atempo={state['config']['speed']},loudnorm=I=-19:TP=-2:LRA=11",
              "-c:a", "libmp3lame", "-b:a", "128k", str(mp3_temp)])
        mp3_temp.replace(mp3)
    metadata = folder / "chapters" / "chapters.ffmeta"
    _ffmetadata(state, durations, metadata)
    concat = _ffconcat(chapter_wavs, folder / "book.wav")
    output = folder / "book.m4b"
    temp = folder / "book.part.m4b"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
               "-safe", "0", "-i", str(concat), "-i", str(metadata)]
    # Covers come from validated in-archive data, never from EPUB-supplied file paths.
    cover = state.get("cover_path")
    coverfile = None
    if cover:
        import zipfile
        with zipfile.ZipFile(folder / "source.epub") as archive:
            ext = Path(cover).suffix.lower()
            if ext in {".jpg", ".jpeg", ".png"}:
                coverfile = folder / ("cover" + ext)
                coverfile.write_bytes(archive.read(cover))
                command += ["-i", str(coverfile)]
    command += ["-map", "0:a:0", "-map_metadata", "1", "-map_chapters", "1",
                "-af", f"atempo={state['config']['speed']},loudnorm=I=-19:TP=-2:LRA=11",
                "-c:a", "aac", "-b:a", "128k"]
    if coverfile:
        command += ["-map", "2:v:0", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    command += ["-f", "mp4", str(temp)]
    _run(command)
    if not temp.exists() or temp.stat().st_size < 1024:
        raise RuntimeError("M4B fehlt oder ist unplausibel klein")
    _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
          "-of", "default=noprint_wrappers=1", str(temp)])
    temp.replace(output)
    return output


def quality(book_id: str, *, asr: bool = False) -> dict:
    state = load(book_id)
    results = []
    for item in state["segments"]:
        file = _file(book_id, item, _signature(state, item))
        row = {"id": item["id"], "exists": file.exists(),
               "warning": item.get("warning")}
        if file.exists():
            try:
                row.update(inspect_wav(file))
                if row["silence_share"] > .8 or row["peak_clipped_share"] > .001:
                    row["warning"] = "Auffällige Stille oder Clipping; bitte anhören"
            except (ValueError, OSError, EOFError) as exc:
                row["warning"] = "Defektes Audio: " + str(exc)
        results.append(row)
    if asr:
        from faster_whisper import WhisperModel
        from difflib import SequenceMatcher
        # Explicit opt-in only; an ASR discrepancy is NOT proof of a TTS mistake.
        recognizer = WhisperModel("medium", device="cuda", compute_type="float16")
        for row, item in zip(results, state["segments"]):
            if row["exists"]:
                file = _file(book_id, item, _signature(state, item))
                tokens, _ = recognizer.transcribe(str(file), language="de")
                recognized = " ".join(t.text for t in tokens)
                row["asr_similarity"] = round(SequenceMatcher(
                    None, item["text"].casefold(), recognized.casefold()).ratio(), 3)
                if row["asr_similarity"] < .85:
                    row["warning"] = "ASR-Abweichung; manuelle Nachprüfung erforderlich"
        del recognizer
    report = {"book": book_id, "asr_enabled": asr, "segments": results,
              "missing": sum(not r["exists"] for r in results),
              "manual_review_required": True, "exclusions": state["exclusions"],
              "warnings": [r for r in results if r.get("warning")],
              "summary": "Automatische Audioindikatoren ersetzen keinen Hörtest."}
    atomic_json(project_path(book_id) / "quality.json", report)
    return report
