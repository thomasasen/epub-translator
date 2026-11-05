"""Synthetic EPUB regression tests for audit_epub.py; no GPU or network required."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from audit_epub import audit

NS = "http://www.w3.org/1999/xhtml"


def make_epub(path, paragraphs, with_link=False, images=0):
    container = (
        '<?xml version="1.0"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>'
    )
    manifest = ''.join(
        f'<item id="c{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(paragraphs))
    )
    manifest += ''.join(
        f'<item id="img{i}" href="img{i}.png" media-type="image/png"/>'
        for i in range(images)
    )
    spine = ''.join(f'<itemref idref="c{i}"/>' for i in range(len(paragraphs)))
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        f'<manifest>{manifest}</manifest><spine>{spine}</spine></package>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/book.opf", opf)
        for i, paragraph in enumerate(paragraphs):
            link = '<a href="#note1">ref</a>' if with_link else ''
            content = (
                f'<html xmlns="{NS}"><body><h1>Chapter {i+1}</h1>'
                f'<p id="p{i}">{paragraph}{link}</p></body></html>'
            )
            archive.writestr(f"OEBPS/chapter{i}.xhtml", content)
        for i in range(images):
            archive.writestr(f"OEBPS/img{i}.png", b"fakepng")


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source.epub"
        self.target = Path(self.temp.name) / "translated.epub"
        self.english = "This is a long paragraph about consistent terminology and full meaning. " * 5
        self.german = "Dies ist ein langer Absatz über einheitliche Begriffe und vollständige Bedeutung. " * 5

    def test_healthy_translation(self):
        make_epub(self.source, [self.english], with_link=True, images=1)
        make_epub(self.target, [self.german], with_link=True, images=1)
        report = audit(self.source, self.target)
        self.assertTrue(report["ok"])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(len(report["chapter_stats"]), 1)

    def test_missing_chapter_is_critical(self):
        make_epub(self.source, [self.english, self.english])
        make_epub(self.target, [self.german])
        report = audit(self.source, self.target)
        self.assertFalse(report["ok"])
        self.assertTrue(any("Spine chapter count" in msg for msg in report["critical"]))

    def test_empty_translation_is_critical(self):
        make_epub(self.source, [self.english])
        make_epub(self.target, [""])
        report = audit(self.source, self.target)
        self.assertFalse(report["ok"])
        self.assertTrue(any("blank after translation" in msg or "major omission" in msg for msg in report["critical"]))

    def test_unchanged_passage_warns(self):
        make_epub(self.source, [self.english])
        make_epub(self.target, [self.english])
        report = audit(self.source, self.target)
        self.assertTrue(report["ok"])
        self.assertTrue(any("unchanged" in msg for msg in report["warnings"]))

    def test_lost_link_warns(self):
        make_epub(self.source, [self.english], with_link=True)
        make_epub(self.target, [self.german], with_link=False)
        report = audit(self.source, self.target)
        self.assertTrue(any("hyperlink count" in msg for msg in report["warnings"]))

    def test_missing_image_asset_is_critical(self):
        make_epub(self.source, [self.english])
        make_epub(self.target, [self.german], images=1)
        # Remove image payload but keep the OPF manifest reference.
        with zipfile.ZipFile(self.target) as original_zip:
            contents = {entry.filename: original_zip.read(entry.filename)
                        for entry in original_zip.infolist()
                        if not entry.filename.endswith("img0.png")}
        with zipfile.ZipFile(self.target, "w") as modified_zip:
            for name, value in contents.items():
                modified_zip.writestr(name, value)
        report = audit(self.source, self.target)
        self.assertFalse(report["ok"])
        self.assertTrue(any("missing files" in msg for msg in report["critical"]))

    def test_malformed_epub_is_critical(self):
        self.source.write_bytes(b"not an epub")
        make_epub(self.target, [self.german])
        report = audit(self.source, self.target)
        self.assertFalse(report["ok"])
        self.assertTrue(report["critical"])


if __name__ == "__main__":
    unittest.main()
