"""German TTS provider safeguards: real German preset, reference cache, no GPU needed for CI."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from audiobook import german_reference, pipeline
from audiobook.engine import MODEL_IDS, ThorstenCosyVoiceEngine


class GermanVoiceTests(unittest.TestCase):
    def test_default_is_german_native_not_ryan(self):
        self.assertEqual(pipeline.SETTINGS["backend"], "qwen-base-german")
        self.assertEqual(pipeline.SETTINGS["speaker"], "Thorsten")
        self.assertEqual(pipeline.SETTINGS["speed"], 1.05)
        self.assertIn("qwen-base-german", MODEL_IDS)
        self.assertIn("cosyvoice-thorsten", MODEL_IDS)
        self.assertEqual(pipeline._post_speed(pipeline.SETTINGS), 1.05)
        self.assertEqual(pipeline._post_speed(
            {**pipeline.SETTINGS, "backend": "cosyvoice-thorsten"}), 1.0)

    def test_accidental_ryan_selection_for_german_backend_rejected(self):
        with self.assertRaisesRegex(ValueError, "Thorsten"):
            pipeline.checked_config({"speaker": "Ryan"})
        with self.assertRaisesRegex(ValueError, "Thorsten"):
            pipeline.checked_config({"backend": "cosyvoice-thorsten", "speaker": "Ryan"})
        cfg = pipeline.checked_config({"backend": "qwen-customvoice", "speaker": "Ryan"})
        self.assertEqual(cfg["backend"], "qwen-customvoice")

    def test_pinned_cc0_recording_selection(self):
        entry = {
            "text": "Der wichtigste Teil einer guten Vertriebsstrategie besteht darin, den Kunden wirklich zu verstehen.",
            "audio": [{"src": "https://datasets-server.huggingface.co/assets/reference.wav"}],
            "microphone": "good_rodePodcaster",
            "speaker": "Thorsten Müller",
            "durationSeconds": 7.8,
            "id": "sample",
        }
        response = json.dumps({"rows": [{"row_idx": 4, "row": entry}]}).encode()
        with patch.object(german_reference, "_read_https", return_value=response) as rd:
            row, src = german_reference._dataset_row()
        self.assertEqual(row["text"], entry["text"])
        self.assertEqual(src, entry["audio"][0]["src"])
        self.assertIn("TV-2022.10-Neutral", rd.call_args.args[0])

    def test_reference_audio_cached_with_exact_transcript(self):
        import shutil
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg fehlt")
        text = "Die aktuelle Situation in Unternehmen erfordert eine strukturierte Vertriebsführung."
        samples = io.BytesIO()
        with wave.open(samples, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes((b"\x20\x00" * (24000 * 6)))
        entry = {"text": text, "id": "one"}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(german_reference, "CACHE", Path(tmp)), \
             patch.object(german_reference, "_dataset_row", return_value=(entry, "https://datasets-server.huggingface.co/assets/x.wav")) as rows, \
             patch.object(german_reference, "_read_https", return_value=samples.getvalue()) as read:
            ref, spoken = german_reference.ensure_thorsten_reference()
            self.assertTrue(ref.is_file())
            self.assertEqual(spoken, text)
            self.assertEqual(json.loads((Path(tmp) / "thorsten-neutral-2022.json").read_text())["license"], "CC0-1.0")
            again, t2 = german_reference.ensure_thorsten_reference()
            self.assertEqual((again, t2), (ref, text))
            rows.assert_called_once()
            read.assert_called_once()

    def test_reject_external_untrusted_voice_source(self):
        with self.assertRaisesRegex(ValueError, "Unerwartete"):
            german_reference._read_https("http://127.0.0.1/admin", 100)
        with self.assertRaisesRegex(ValueError, "Unerwartete"):
            german_reference._read_https("https://evil.example.com/audio", 100)


if __name__ == "__main__":
    unittest.main()
