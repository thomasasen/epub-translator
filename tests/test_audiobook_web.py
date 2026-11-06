"""FastAPI browser/API smoke tests without NVIDIA GPU."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from audiobook import pipeline, server
from test_audiobook import fixture


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.epub = self.root / "input.epub"
        fixture(self.epub)
        self.patch1 = patch.object(pipeline, "ROOT", self.root / "audiobooks")
        self.patch2 = patch.object(server, "ROOT", self.root / "audiobooks")
        self.patch3 = patch.object(server, "TRANSLATED", self.root / "translated")
        self.patch1.start()
        self.patch2.start()
        self.patch3.start()
        self.addCleanup(self.patch1.stop)
        self.addCleanup(self.patch2.stop)
        self.addCleanup(self.patch3.stop)
        self.client = TestClient(server.app)

    def test_public_frontend_and_health_without_password(self):
        r = self.client.get("/audiobook/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Fachbücher als Hörbuch", r.text)
        self.assertEqual(self.client.get("/audiobook/health").status_code, 200)
        self.assertEqual(self.client.get("/audiobook/api/books").json(), [])

    def test_upload_config_gate_and_qa(self):
        with self.epub.open("rb") as file:
            response = self.client.post("/audiobook/api/upload", files={
                "file": ("book.epub", file, "application/epub+zip")})
        self.assertEqual(response.status_code, 200, response.text)
        book_id = response.json()["id"]
        book = self.client.get("/audiobook/api/books/" + book_id).json()
        self.assertEqual(book["title"], "Fachbuch")
        self.assertEqual(len(book["chapters"]), 2)
        path = "/audiobook/api/books/" + book_id
        self.assertEqual(self.client.post(path + "/approve").status_code, 400)
        q = self.client.get(path + "/quality").json()
        self.assertGreater(q["missing"], 0)
        response = self.client.put(path + "/config", json={
            "settings": {"quality": "careful", "speed": 0.9},
            "glossary": {"CRM": "C R M"}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLessEqual(response.json()["config"]["max_chars"], 300)
        self.assertIsNone(response.json()["approved_fingerprint"])

    def test_term_preview_using_mock_backend(self):
        import shutil
        if shutil.which("ffmpeg") is None:
            self.skipTest("FFmpeg fehlt")
        with patch.dict(os.environ, {"AUDIOBOOK_TEST_MOCK": "1"}):
            with self.epub.open("rb") as file:
                imported = self.client.post("/audiobook/api/upload", files={
                    "file": ("test.epub", file, "application/epub+zip")})
            self.assertEqual(imported.status_code, 200, imported.text)
            book_id = imported.json()["id"]
            url = "/audiobook/api/books/" + book_id
            config = self.client.put(url + "/config", json={
                "settings": {"backend": "mock"}, "glossary": {"CRM": "C R M"}})
            self.assertEqual(config.status_code, 200, config.text)
            spoken = self.client.post(url + "/term-preview", json={"phrase": "CRM"})
            self.assertEqual(spoken.status_code, 200, spoken.text)
            token = spoken.json()["token"]
            audio = self.client.get(url + "/download/term?token=" + token)
            self.assertEqual(audio.status_code, 200)
            self.assertGreater(len(audio.content), 1000)
            self.assertEqual(self.client.get(url + "/download/term?token=../bad").status_code, 400)

    def test_invalid_upload_and_path(self):
        r = self.client.post("/audiobook/api/upload", files={
            "file": ("invalid.epub", b"not an epub", "application/epub+zip")})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/audiobook/api/import-translated", json={
            "name": "../private.epub"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
