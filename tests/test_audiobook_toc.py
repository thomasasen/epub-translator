"""TOC skipping must preserve the true book content and remain configurable."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from audiobook import core, pipeline

CONTAINER = ('<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
             '<rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>')


def make_book(path: Path, toc_content: str, *, properties: str = "") -> None:
    manifest = (
        f'<item id="toc" href="contents.xhtml" media-type="application/xhtml+xml" {properties}/>'
        '<item id="foreword" href="foreword.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="body" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    opf = ('<package xmlns="http://www.idpf.org/2007/opf">'
           '<metadata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Test</dc:title></metadata>'
           '<manifest>' + manifest + '</manifest><spine>'
           '<itemref idref="toc"/><itemref idref="foreword"/><itemref idref="body"/>'
           '</spine></package>')
    preface = '<h1>Vorwort</h1><p>Ein Vorwort, das gelesen werden muss.</p>'
    chapter = '<h1>Kapitel eins</h1><p>Das erste wichtige Kapitel über Führung.</p>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/package.opf", opf)
        for name, text in [("contents.xhtml", toc_content),
                           ("foreword.xhtml", preface), ("chapter.xhtml", chapter)]:
            z.writestr("OEBPS/" + name,
                       '<html xmlns="http://www.w3.org/1999/xhtml"'
                       ' xmlns:epub="http://www.idpf.org/2007/ops"><body>' +
                       text + '</body></html>')


class SkipTocTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "book.epub"

    def test_default_skips_contents_but_reads_foreword_and_body(self):
        make_book(self.path, '<h1>Inhaltsverzeichnis</h1>'
                 '<ol><li><a href="foreword.xhtml">Vorwort</a></li>'
                 '<li><a href="chapter.xhtml">Kapitel eins</a></li></ol>')
        doc = core.read_epub(self.path)
        self.assertEqual([c["title"] for c in doc["chapters"]], ["Vorwort", "Kapitel eins"])
        self.assertEqual([c["id"] for c in doc["chapters"]], [1, 2])
        self.assertTrue(any("Inhaltsverzeichnis ausgelassen" in e["reason"]
                            for e in doc["exclusions"]))
        full = core.read_epub(self.path, skip_toc=False)
        self.assertEqual(len(full["chapters"]), 3)
        self.assertEqual(full["chapters"][0]["title"], "Inhaltsverzeichnis")
        self.assertEqual(full["exclusions"], [])

    def test_epub_nav_property_skips_even_without_heading(self):
        make_book(self.path, '<nav epub:type="toc"><ol>'
                 '<li><a href="chapter.xhtml">Kapitel eins</a></li>'
                 '</ol></nav><p>Übersicht</p>', properties='properties="nav"')
        doc = core.read_epub(self.path)
        self.assertEqual([c["title"] for c in doc["chapters"]], ["Vorwort", "Kapitel eins"])
        self.assertEqual(len(doc["exclusions"]), 1)

    def test_epub_toc_semantics_skip_even_with_unusual_title(self):
        make_book(self.path, '<section epub:type="toc"><h2>Übersicht</h2>'
                 '<ul><li>Vorwort</li></ul></section>')
        doc = core.read_epub(self.path)
        self.assertEqual(len(doc["chapters"]), 2)

    def test_preserve_narrative_when_contents_heading_is_misleading(self):
        make_book(self.path, '<h1>Contents</h1><p>' +
                 'Ein ausführlicher erläuternder Fachtext mit weiterführenden Gedanken. ' * 6 +
                 '</p>')
        doc = core.read_epub(self.path)
        self.assertEqual(len(doc["chapters"]), 3)
        self.assertEqual(doc["chapters"][0]["title"], "Contents")

    def test_preserve_a_normal_chapter_about_contents(self):
        make_book(self.path, '<h1>Inhaltliche Übersicht</h1>'
                 '<p>Unser Konzept wird hier im Detail vorgestellt.</p>')
        doc = core.read_epub(self.path)
        self.assertEqual(len(doc["chapters"]), 3)

    def test_settings_toggle_rebuilds_without_touching_epub(self):
        make_book(self.path, '<h1>Inhaltsverzeichnis</h1>'
                 '<p>Vorwort 1. Kapitel eins 2.</p>')
        before = self.path.read_bytes()
        with patch.object(pipeline, "ROOT", Path(self.directory.name) / "projects"), \
             patch.dict(os.environ, {"AUDIOBOOK_TEST_MOCK": "1"}):
            book_id = pipeline.create_book(self.path, config={"backend": "mock"})
            s = pipeline.load(book_id)
            self.assertTrue(s["config"]["skip_toc"])
            self.assertEqual(len(s["chapters"]), 2)
            pipeline.configure(book_id, {"skip_toc": False})
            s = pipeline.load(book_id)
            self.assertEqual(len(s["segments"]), 6)
            self.assertEqual(len(s["chapters"]), 3)  # metadata and chapter marks rebuilt
            self.assertIsNone(s["approved_fingerprint"])
            self.assertEqual(s["exclusions"], [])
            pipeline.configure(book_id, {"skip_toc": True})
            s = pipeline.load(book_id)
            self.assertEqual(len(s["segments"]), 4)
            self.assertEqual(before, self.path.read_bytes())

    def test_reject_nonboolean_setting(self):
        with self.assertRaisesRegex(ValueError, "skip_toc"):
            pipeline.checked_config({"skip_toc": "false"})


if __name__ == "__main__":
    unittest.main()
