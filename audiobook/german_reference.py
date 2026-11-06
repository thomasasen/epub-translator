"""CC0 German reference recording for Qwen3-TTS Base voice cloning.

Downloads one neutral, studio-recorded Thorsten-Voice sentence on first use
from the official public Hugging Face dataset server. The recorded transcript
is saved verbatim for Qwen's ICL voice-cloning path. No audio is bundled or
submitted to cloud TTS. Cache lives on the persistent /workspace volume.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from .core import atomic_json

DATASET = "Thorsten-Voice/TV-44kHz-Full"
CONFIG = "TV-2022.10-Neutral"
LICENSE = "CC0-1.0"
CACHE = Path(os.getenv("AUDIOBOOK_VOICE_CACHE", "/workspace/epub-translator/voices"))
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_ROWS_BYTES = 3 * 1024 * 1024
SOURCE_HOST = "datasets-server.huggingface.co"


def _read_https(url: str, limit: int) -> bytes:
    parts = urllib.parse.urlsplit(url)
    # Prevent SSRF via redirects or unexpected dataset asset URLs.
    if parts.scheme != "https" or not (parts.hostname == "huggingface.co" or
        parts.hostname == SOURCE_HOST or
        (parts.hostname or "").endswith(".huggingface.co")):
        raise ValueError("Unerwartete Hugging-Face-Quelladresse")
    request = urllib.request.Request(url, headers={"User-Agent": "epub-translator-german-voice/1"})
    with urllib.request.urlopen(request, timeout=40) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != "https" or not (final.hostname == "huggingface.co" or
                final.hostname == SOURCE_HOST or
                (final.hostname or "").endswith(".huggingface.co")):
            raise ValueError("Unzulässige Weiterleitung beim Referenzaudio")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Deutsches Referenzaudio zu groß")
    return data


def _dataset_row() -> tuple[dict, str]:
    query = urllib.parse.urlencode({
        "dataset": DATASET, "config": CONFIG,
        "split": "train", "offset": 0, "length": 100,
    })
    data = json.loads(_read_https("https://" + SOURCE_HOST + "/rows?" + query, MAX_ROWS_BYTES))
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("Fehlerhafte Hugging-Face-Datensatzantwort")
    candidates = []
    for result in rows:
        entry = result.get("row", {})
        if not isinstance(entry, dict):
            continue
        text = entry.get("text", "")
        audio = entry.get("audio") or {}
        if not isinstance(audio, dict):
            continue
        src = audio.get("src")
        mic = str(entry.get("microphone", "")).lower()
        speaker = str(entry.get("speaker", "")).lower()
        duration = float(entry.get("durationSeconds") or 0)
        if (isinstance(src, str) and isinstance(text, str) and 70 <= len(text) <= 170
                and 5 <= duration <= 15 and "rode" in mic and "thorsten" in speaker):
            candidates.append((result.get("row_idx", 0), entry, src))
    if not candidates:
        raise RuntimeError(
            "Keine passende deutsche Referenzaufnahme im öffentlichen Thorsten-Datensatz gefunden. "
            "Bitte die Datensatzquelle prüfen; es wird NICHT auf die englische Ryan-Stimme gewechselt."
        )
    _, selected, src = sorted(candidates, key=lambda x: x[0])[0]
    return selected, src


def ensure_thorsten_reference() -> tuple[Path, str]:
    """Return cached WAV and its exact German transcript; fetch only on first use."""
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / "thorsten-neutral-2022.wav"
    manifest = CACHE / "thorsten-neutral-2022.json"
    if target.is_file() and manifest.is_file():
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            with wave.open(str(target), "rb") as audio:
                seconds = audio.getnframes() / audio.getframerate()
            if 3 <= seconds <= 20 and meta.get("dataset") == DATASET and meta.get("text"):
                return target, meta["text"]
        except (ValueError, OSError, KeyError, json.JSONDecodeError, wave.Error):
            pass

    try:
        row, url = _dataset_row()
        raw = _read_https(url, MAX_AUDIO_BYTES)
    except Exception as exc:
        raise RuntimeError(
            "Die deutsche Thorsten-Referenz konnte nicht von Hugging Face geladen werden. "
            "Prüfe die Netzwerkverbindung des Pods bzw. versuche es erneut: " + str(exc)
        ) from exc

    if not raw:
        raise RuntimeError("Leere Thorsten-Referenzaufnahme")
    with tempfile.TemporaryDirectory(dir=CACHE, prefix="thorsten-") as tmp:
        src = Path(tmp) / "reference.audio"
        wav = Path(tmp) / "reference.wav"
        src.write_bytes(raw)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(src), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode or not wav.is_file():
            raise RuntimeError("Deutsche Referenz konnte nicht in WAV umgewandelt werden: " +
                               result.stderr[-400:])
        with wave.open(str(wav), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if not 3 <= seconds <= 20:
            raise RuntimeError("Die deutsche Referenz hat eine ungeeignete Länge")
        os.replace(wav, target)
        atomic_json(manifest, {
            "dataset": DATASET, "config": CONFIG,
            "text": row["text"], "license": LICENSE,
            "speaker": "Thorsten Müller",
            "source": "https://huggingface.co/datasets/" + DATASET,
            "recording_id": row.get("id", ""),
        })
    return target, row["text"]
