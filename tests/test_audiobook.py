"""CPU-only audiobook integration/regression suite with a real FFmpeg export."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from audiobook import core
from audiobook import pipeline


def fixture(path, paragraphs=None, *, table=False, swap=False):
    paragraphs = paragraphs or ["Ein ruhiger Fachtext über Führung und CRM. " * 8,
                                 "Pipeline Forecast 10 Prozent SaaS und EBITDA. " * 8]
    container = ('<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>')
    manifest = ''.join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
                       for i in range(len(paragraphs)))
    spine_ids = list(range(len(paragraphs)))
    if swap:
        spine_ids.reverse()
    spine = ''.join(f'<itemref idref="c{i}"/>' for i in spine_ids)
    opf = ('<package xmlns="http://www.idpf.org/2007/opf"><metadata>'
           '<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Fachbuch</dc:title>'
           '<dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Beispiel</dc:creator>'
           '</metadata><manifest>' + manifest + '</manifest><spine>' + spine + '</spine></package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/package.opf", opf)
        for i, text in enumerate(paragraphs):
            extra = '<table><tr><td>Umsatz 1</td></tr></table>' if table and i == 0 else ''
            z.writestr(f"OEBPS/c{i}.xhtml",
                       f'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                       f'<h1>Kapitel {i + 1}</h1><p>{text}</p>{extra}</body></html>')


class BookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.epub = self.folder / "book.epub"
        fixture(self.epub)

    def test_actual_spine_order(self):
        fixture(self.epub, swap=True)
        result = core.read_epub(self.epub)
        self.assertEqual(result["chapters"][0]["title"], "Kapitel 2")
        self.assertEqual(result["metadata"]["author"], "Beispiel")

    def test_tables_are_not_silently_omitted(self):
        fixture(self.epub, table=True)
        data = core.read_epub(self.epub)
        self.assertTrue(any("Tabelle" in row["reason"] for row in data["exclusions"]))

    def test_whole_word_glossary_and_original_unchanged(self):
        original = "CRM CRMS und SaaS."
        spoken = core.apply_glossary(original, {"CRM": "C R M", "SaaS": "Sass"})
        self.assertEqual(spoken, "C R M CRMS und Sass.")
        self.assertEqual(original, "CRM CRMS und SaaS.")

    def test_zip_traversal_rejected(self):
        with zipfile.ZipFile(self.epub, "w") as z:
            z.writestr("../evil", "x")
            z.writestr("META-INF/container.xml", "<container/>")
        with self.assertRaises(ValueError):
            core.validate_epub(self.epub)

    def test_segment_length_rules(self):
        with self.assertRaises(ValueError):
            core.segments([], {}, 50)
        result = core.segments([{"kind": "p", "text": "Eine Aussage. " * 50}], {}, 150)
        self.assertGreater(len(result), 1)
        self.assertTrue(all(x["text"] for x in result))

    def test_project_path_traversal(self):
        with self.assertRaises(ValueError):
            pipeline.project_path("../../etc")

    def test_preview_gate_resume_invalidation_and_export(self):
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            self.skipTest("FFmpeg fehlt")
        with patch.object(pipeline, "ROOT", self.folder / "audiobooks"), \
             patch.dict(os.environ, {"AUDIOBOOK_TEST_MOCK": "1"}):
            book_id = pipeline.create_book(self.epub,
                    config={"backend": "mock", "speaker": "Ryan", "max_chars": 300})
            self.assertTrue(pipeline.load(book_id)["segments"])
            with self.assertRaisesRegex(ValueError, "Freigabe"):
                pipeline.synthesize(book_id)
            preview = pipeline.synthesize(book_id, preview=True)
            self.assertEqual(preview["status"], "preview_ready")
            self.assertTrue((pipeline.project_path(book_id) / "preview.mp3").is_file())
            pipeline.approve(book_id)
            result = pipeline.synthesize(book_id)
            self.assertEqual(result["status"], "completed")
            m4b = pipeline.project_path(book_id) / "book.m4b"
            self.assertGreater(m4b.stat().st_size, 1000)
            out = subprocess.check_output(["ffprobe", "-v", "error",
                  "-show_entries", "chapter=start_time,end_time:format_tags=title,artist",
                  "-of", "json", str(m4b)], text=True)
            info = json.loads(out)
            self.assertEqual(len(info["chapters"]), 2)
            self.assertEqual(info["format"]["tags"]["title"], "Fachbuch")
            q = pipeline.quality(book_id)
            self.assertEqual(q["missing"], 0)
            self.assertTrue(q["manual_review_required"])
            first = pipeline.load(book_id)["segments"][0]
            wav = pipeline._file(book_id, first, pipeline._signature(pipeline.load(book_id), first))
            before = wav.stat().st_mtime_ns
            pipeline.synthesize(book_id)
            self.assertEqual(before, wav.stat().st_mtime_ns)
            pipeline.configure(book_id, {"speaker": "Aiden"})
            self.assertIsNone(pipeline.load(book_id)["approved_fingerprint"])
            with self.assertRaisesRegex(ValueError, "Freigabe"):
                pipeline.synthesize(book_id)

    def test_spoken_number_symbols(self):
        self.assertEqual(core.normalize_spoken("1,5 Mio. € und 12%"),
                         "1,5 Mio. Euro und 12 Prozent")
        self.assertEqual(core.normalize_spoken("1.234,56"), "1.234,56")

    def test_cancel_preserves_valid_segment_and_resumes(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("FFmpeg fehlt")
        from audiobook.engine import MockEngine
        class StopAfterFirst(MockEngine):
            def synthesize(self, *args, **kwargs):
                super().synthesize(*args, **kwargs)
                pipeline.CANCEL_EVENT.set()
                pipeline.STOP_EVENT.set()

        with patch.object(pipeline, "ROOT", self.folder / "audiobooks"), \
             patch.dict(os.environ, {"AUDIOBOOK_TEST_MOCK": "1"}):
            book_id = pipeline.create_book(self.epub, config={"backend": "mock"})
            pipeline.synthesize(book_id, preview=True)
            pipeline.approve(book_id)
            with patch.object(pipeline, "create_engine", return_value=StopAfterFirst()):
                status = pipeline.synthesize(book_id)
            self.assertEqual(status["status"], "cancelled")
            resumed = pipeline.synthesize(book_id)
            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(pipeline.quality(book_id)["missing"], 0)

    def test_audio_header_corruption(self):
        p = self.folder / "bad.wav"
        p.write_bytes(b"not a wav")
        from audiobook.engine import inspect_wav
        with self.assertRaises((ValueError, EOFError, OSError)):
            inspect_wav(p)


if __name__ == "__main__":
    unittest.main()
