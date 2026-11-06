"""Austauschbare Speech-Backends; standardmäßig strikt GPU-basiert."""
from __future__ import annotations

import gc
import math
import os
import struct
import subprocess
import wave
from pathlib import Path

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
COSYVOICE_MODEL_ID = "Thorsten-Voice/CosyVoice3"
MODEL_IDS = {"qwen-customvoice": MODEL_ID, "qwen-base-german": BASE_MODEL_ID,
             "cosyvoice-thorsten": COSYVOICE_MODEL_ID, "mock": "mock-ci"}
VOICES = ("Ryan", "Aiden", "Uncle_Fu", "Serena", "Vivian", "Dylan", "Eric", "Ono_Anna", "Sohee")


def gpu_free_mib() -> int:
    p = subprocess.run(["nvidia-smi", "--query-gpu=memory.free",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True,
                       timeout=15, check=False)
    if p.returncode:
        raise RuntimeError("nvidia-smi fehlgeschlagen: " + p.stderr.strip()[:200])
    values = [int(line.strip()) for line in p.stdout.splitlines() if line.strip().isdigit()]
    if not values:
        raise RuntimeError("GPU nicht erkannt. Kein automatischer CPU-Fallback.")
    return max(values)


def assert_gpu_available(min_free_mib: int = 9000) -> None:
    # Do not launch TTS while an Ollama translation model is still resident.
    # The upstream translator has no safe cross-process job-idle signal.
    import json
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as response:
            resident = json.load(response).get("models", [])
        if resident:
            raise RuntimeError("Ollama-Modell ist geladen: laufende Übersetzung erst beenden und danach Ollama kontrolliert entladen.")
    except (OSError, TimeoutError, ValueError):
        # No Ollama process, e.g. direct CLI use outside the RunPod deployment.
        pass
    if gpu_free_mib() < min_free_mib:
        raise RuntimeError(
            "Zu wenig freier VRAM für hochwertige TTS. "
            "Übersetzung zuerst beenden; danach das geladene Ollama-Modell "
            "manuell mit 'ollama stop MODELL' entladen. Laufende Jobs werden nicht unterbrochen."
        )


def _inspect_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as f:
        rate, frames, channels, width = f.getframerate(), f.getnframes(), f.getnchannels(), f.getsampwidth()
        if not rate or not frames or width not in (2, 4) or channels not in (1, 2):
            raise ValueError("Beschädigte oder leere WAV-Datei")
        total_samples = 0
        clipped = 0
        silent = 0
        sq = 0
        # Scan every 16th sample in blocks, bounded-memory even for hours of speech.
        while True:
            data = f.readframes(8192)
            if not data:
                break
            unit = width * channels
            for off in range(0, len(data) - unit + 1, unit * 16):
                val = int.from_bytes(data[off:off + width], "little", signed=True) / float(1 << (8 * width - 1))
                total_samples += 1
                clipped += abs(val) >= .999
                silent += abs(val) < .0008
                sq += val * val
        duration = frames / rate
        rms = math.sqrt(sq / max(total_samples, 1))
        return {"seconds": round(duration, 2), "sample_rate": rate,
                "peak_clipped_share": round(clipped / max(total_samples, 1), 5),
                "silence_share": round(silent / max(total_samples, 1), 4),
                "rms_dbfs": round(20 * math.log10(max(rms, 1e-9)), 2)}


def inspect_wav(path: Path) -> dict:
    try:
        return _inspect_wav(path)
    except wave.Error as exc:
        raise ValueError("Beschädigter WAV-Header: " + str(exc)) from exc

class MockEngine:
    """Nur für reproduzierbare CI-Tests; niemals als Qualitätsstimme anbieten."""
    model_id = "mock-ci"
    def synthesize(self, text: str, destination: Path, *, speaker: str, instruction: str, seed: int) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            # 0.5 seconds of safe low-amplitude sine wave for CLI/CI.
            samples = [int(1000 * math.sin(2 * math.pi * 220 * n / 24000)) for n in range(12000)]
            wav.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    def close(self) -> None:
        pass


class QwenCustomVoiceEngine:
    """Qwen3-TTS 12Hz 1.7B; keine unbestätigten SSML-/Phonem-Features."""
    model_id = MODEL_ID
    def __init__(self) -> None:
        assert_gpu_available()
        import torch
        from qwen_tts import Qwen3TTSModel
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA nicht verfügbar")
        self.torch = torch
        self.model = Qwen3TTSModel.from_pretrained(
            MODEL_ID, device_map="cuda:0", dtype=torch.bfloat16,
            attn_implementation=os.getenv("AUDIOBOOK_ATTENTION", "sdpa"))
    def synthesize(self, text: str, destination: Path, *, speaker: str, instruction: str, seed: int) -> None:
        import soundfile as sf
        if speaker not in VOICES:
            raise ValueError("Unbekannte Qwen-Sprecherstimme")
        self.torch.manual_seed(seed)
        self.torch.cuda.manual_seed_all(seed)
        try:
            waves, sample_rate = self.model.generate_custom_voice(
                text=text, language="German", speaker=speaker,
                instruct=instruction)
            if not waves or not len(waves[0]):
                raise RuntimeError("Leere TTS-Ausgabe")
            destination.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(destination), waves[0], sample_rate, subtype="PCM_16")
        except self.torch.cuda.OutOfMemoryError as exc:
            raise RuntimeError("GPU-Out-of-Memory; TTS angehalten, Segmente bleiben erhalten") from exc
    def close(self) -> None:
        del self.model
        gc.collect()
        self.torch.cuda.empty_cache()



def cosyvoice_available() -> bool:
    """Only the official Thorsten service on the loopback interface is accepted."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
            body = json.load(response)
        return body.get("status") == "ok" and "Thorsten" in str(body.get("model", ""))
    except (OSError, ValueError, TimeoutError, KeyError):
        return False


class QwenGermanCloneEngine:
    """Qwen Base with a genuine German CC0 speaker reference (not Ryan)."""
    model_id = BASE_MODEL_ID

    def __init__(self) -> None:
        from .german_reference import ensure_thorsten_reference
        reference, reference_text = ensure_thorsten_reference()
        assert_gpu_available()
        import torch
        from qwen_tts import Qwen3TTSModel
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA nicht verfügbar")
        self.torch = torch
        self.model = Qwen3TTSModel.from_pretrained(
            BASE_MODEL_ID, device_map="cuda:0", dtype=torch.bfloat16,
            attn_implementation=os.getenv("AUDIOBOOK_ATTENTION", "sdpa"))
        # The exact reference transcript improves pronunciation/style conditioning.
        self.voice_prompt = self.model.create_voice_clone_prompt(
            ref_audio=str(reference), ref_text=reference_text, x_vector_only_mode=False)

    def synthesize(self, text: str, destination: Path, *, speaker: str,
                   instruction: str, seed: int, speed: float = 1.0) -> None:
        import soundfile as sf
        if speaker != "Thorsten":
            raise ValueError("Qwen-Base-Deutsch verwendet ausschließlich Thorsten als Referenzstimme")
        self.torch.manual_seed(seed)
        self.torch.cuda.manual_seed_all(seed)
        try:
            waves, sample_rate = self.model.generate_voice_clone(
                text=text, language="German", voice_clone_prompt=self.voice_prompt)
            if not waves or not len(waves[0]):
                raise RuntimeError("Leere deutsche TTS-Ausgabe")
            destination.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(destination), waves[0], sample_rate, subtype="PCM_16")
        except self.torch.cuda.OutOfMemoryError as exc:
            raise RuntimeError("GPU-Speicher für Qwen Base nicht ausreichend") from exc

    def close(self) -> None:
        del self.model
        del self.voice_prompt
        gc.collect()
        self.torch.cuda.empty_cache()


class ThorstenCosyVoiceEngine:
    """Use the official separate CosyVoice3-Thorsten HTTP service on localhost."""
    model_id = COSYVOICE_MODEL_ID

    def __init__(self) -> None:
        if not cosyvoice_available():
            raise RuntimeError(
                "Thorsten CosyVoice3 ist nicht gestartet. Starte den offiziellen "
                "CosyVoice-Docker-Dienst mit GPU lokal auf Port 8000 oder wähle "
                "Qwen3 Base Deutsch (keine zusätzliche Docker-Installation nötig).")
        assert_gpu_available(min_free_mib=0)

    def synthesize(self, text: str, destination: Path, *, speaker: str,
                   instruction: str, seed: int, speed: float = 1.0) -> None:
        import urllib.parse
        import urllib.request
        if speaker != "Thorsten":
            raise ValueError("CosyVoice3-Thorsten hat eine feste deutsche Stimme")
        payload = urllib.parse.urlencode({"text": text, "speed": f"{speed:.3f}"}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8000/tts", data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=360) as response:
                data = response.read(15 * 1024 * 1024 + 1)
        except (OSError, TimeoutError) as exc:
            raise RuntimeError("Thorsten-CosyVoice3-Dienst nicht erreichbar: " + str(exc)) from exc
        if len(data) > 15 * 1024 * 1024 or len(data) < 100 or not data.startswith(b"RIFF"):
            raise RuntimeError("CosyVoice3 lieferte keine gültige WAV-Datei")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def close(self) -> None:
        pass

def create_engine(name: str):
    if name == "qwen-customvoice":
        return QwenCustomVoiceEngine()
    if name == "qwen-base-german":
        return QwenGermanCloneEngine()
    if name == "cosyvoice-thorsten":
        return ThorstenCosyVoiceEngine()
    if name == "mock" and os.getenv("AUDIOBOOK_TEST_MOCK") == "1":
        return MockEngine()
    raise ValueError("Nicht unterstütztes Speech-Backend")
