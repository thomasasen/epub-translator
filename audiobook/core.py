"""Sichere EPUB-Lesereihenfolge, Ausspracheglossar und konservative Segmentierung."""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
MAX_EPUB_SIZE = 150 * 1024 * 1024
MAX_UNCOMPRESSED = 350 * 1024 * 1024
MAX_ZIP_RATIO = 150
MAX_ENTRY = 30 * 1024 * 1024
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = HEADINGS | {"p", "li", "blockquote", "pre", "figcaption"}
DEFAULT_GLOSSARY = {
    "MEDDPICC": "M E D D P I C C",
    "CRM": "C R M", "SaaS": "Sass", "ARR": "A R R", "MRR": "M R R",
    "EBITDA": "E B I T D A", "ROI": "R O I", "SQL": "S Q L",
}
_SENTENCES = re.compile(r"(?<=[.!?;:])\s+(?=[A-ZÄÖÜ\d„\"'])")
_SPACE = re.compile(r"\s+")


def plain(value: str) -> str:
    return _SPACE.sub(" ", value or "").strip()


def checksum(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def safe_path(root: Path, name: str) -> Path:
    root = root.resolve()
    target = (root / name).resolve()
    if target == root or root not in target.parents:
        raise ValueError("Pfad außerhalb des Projektverzeichnisses")
    return target


def _internal(base: str, href: str) -> str:
    href = unquote(href.split("#", 1)[0].split("?", 1)[0])
    if not href or href.startswith("/") or "\\" in href:
        raise ValueError("Unsicherer EPUB-Verweis")
    normalized = posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    if normalized.startswith("../") or normalized in {".", ".."}:
        raise ValueError("EPUB-Verweis verlässt Archiv")
    return normalized


def validate_epub(path: Path) -> None:
    if path.suffix.lower() != ".epub" or path.stat().st_size > MAX_EPUB_SIZE:
        raise ValueError("Ungültige oder zu große EPUB-Datei")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if len(entries) > 15000:
            raise ValueError("EPUB mit zu vielen Einträgen")
        total = 0
        for e in entries:
            normalized = posixpath.normpath(e.filename)
            if (e.filename.startswith("/") or "\\" in e.filename or
                    normalized.startswith("../") or normalized == ".."):
                raise ValueError("Unsicherer ZIP-Pfad")
            total += e.file_size
            if (e.file_size > MAX_ENTRY or total > MAX_UNCOMPRESSED or
                    e.file_size > MAX_ZIP_RATIO * max(1, e.compress_size)):
                raise ValueError("Mögliche EPUB-ZIP-Bombe")
        if "META-INF/container.xml" not in z.namelist():
            raise ValueError("Kein gültiges EPUB")


def _tag(elem: ET.Element) -> str:
    return elem.tag.rsplit("}", 1)[-1].lower()


def _blocks(root: ET.Element, *, captions: bool, notes: bool) -> tuple[list[dict], list[str]]:
    blocks, exclusions = [], []
    def walk(node: ET.Element, skip: bool = False) -> None:
        tag = _tag(node)
        epub_type = " ".join(v for k, v in node.attrib.items() if k.endswith("}type") or k == "epub:type")
        excluded = skip or (not notes and any(x in epub_type for x in ("footnote", "endnote", "noteref")))
        if excluded:
            if not skip:
                exclusions.append("Fußnote/Endnote ausgelassen: " + plain("".join(node.itertext()))[:160])
            return
        if tag in {"script", "style", "nav"}:
            return
        if tag == "table":
            exclusions.append("Tabelle zur manuellen Prüfung: " + plain("".join(node.itertext()))[:200])
            return
        if tag == "img":
            exclusions.append("Abbildung nicht vertont: " + node.attrib.get("alt", "")[:160])
            return
        if tag == "figcaption" and not captions:
            exclusions.append("Bildunterschrift ausgelassen: " + plain("".join(node.itertext()))[:160])
            return
        if tag in BLOCKS:
            text = plain("".join(node.itertext()))
            if text:
                blocks.append({"kind": "heading" if tag in HEADINGS else tag, "text": text})
            return
        for child in node:
            walk(child)
    body = next((e for e in root.iter() if _tag(e) == "body"), root)
    walk(body)
    return blocks, exclusions


def read_epub(path: Path, *, captions: bool = False, notes: bool = False) -> dict:
    validate_epub(path)
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = next((e for e in container.iter() if _tag(e) == "rootfile"), None)
        if rootfile is None:
            raise ValueError("EPUB ohne OPF")
        opf_path = rootfile.attrib["full-path"]
        package = ET.fromstring(z.read(opf_path))
        meta = {"title": "Unbekannter Titel", "author": "Unbekannter Autor", "cover": None}
        for e in package.iter():
            if e.tag == f"{{{DC}}}title" and e.text:
                meta["title"] = plain(e.text)
            if e.tag == f"{{{DC}}}creator" and e.text:
                meta["author"] = plain(e.text)
        manifest = {}
        for e in package.iter():
            if _tag(e) == "item":
                try:
                    location = _internal(opf_path, e.attrib["href"])
                except (KeyError, ValueError):
                    raise ValueError("Ungültiger EPUB-Manifestpfad") from None
                manifest[e.attrib.get("id", "")] = {
                    "path": location, "type": e.attrib.get("media-type", ""),
                    "properties": e.attrib.get("properties", "")}
                if "cover-image" in e.attrib.get("properties", ""):
                    if e.attrib.get("media-type", "").startswith("image/"):
                        meta["cover"] = location
        chapters = []
        for e in package.iter():
            if _tag(e) != "itemref" or e.attrib.get("linear", "yes") == "no":
                continue
            item = manifest.get(e.attrib.get("idref"))
            if not item:
                raise ValueError("Spine enthält unbekanntes Item")
            if item["type"] not in {"application/xhtml+xml", "text/html"}:
                continue
            root = ET.fromstring(z.read(item["path"]))
            blocks, excluded = _blocks(root, captions=captions, notes=notes)
            if not blocks:
                continue
            title = next((b["text"] for b in blocks if b["kind"] == "heading"), f"Kapitel {len(chapters)+1}")
            chapters.append({"id": len(chapters) + 1, "title": title,
                             "blocks": blocks, "exclusions": excluded,
                             "characters": sum(len(b["text"]) for b in blocks)})
        if not chapters:
            raise ValueError("EPUB enthält keine vorlesbaren Kapitel")
        return {"metadata": meta, "chapters": chapters,
                "exclusions": [{"chapter": c["id"], "reason": x}
                               for c in chapters for x in c["exclusions"]]}


def apply_glossary(text: str, glossary: dict[str, str]) -> str:
    """Nur Sprechtext beeinflussen; keine willkürlichen Teilwortersetzungen."""
    result = text
    for source, spoken in sorted(glossary.items(), key=lambda kv: -len(kv[0])):
        if not source or not spoken or len(source) > 100 or len(spoken) > 180:
            raise ValueError("Ungültiger Glossareintrag")
        pattern = r"(?<!\w)" + re.escape(source) + r"(?!\w)"
        result = re.sub(pattern, lambda _: spoken, result, flags=re.IGNORECASE)
    return result


def normalize_spoken(text: str) -> str:
    """Nur eindeutige Symbole aussprechen; Zahlenwerte nicht umrechnen."""
    text = re.sub(r"(?<=\d)\s*%", " Prozent", text)
    text = re.sub(r"(?<=\d)\s*€", " Euro", text)
    text = text.replace(" €", " Euro").replace("€ ", "Euro ")
    return text


def segments(blocks: list[dict], glossary: dict[str, str], max_chars: int = 400) -> list[dict]:
    if not 120 <= max_chars <= 1200:
        raise ValueError("Segmentlänge muss 120..1200 Zeichen betragen")
    output = []
    for block in blocks:
        original = block["text"]
        spoken = normalize_spoken(apply_glossary(original, glossary))
        sentences = _SENTENCES.split(spoken)
        current = ""
        for s in sentences:
            if len(s) > max_chars:
                # Prefer clause boundaries; flag any oversized unbroken sentence for review.
                if current:
                    output.append({"text": current, "kind": block["kind"]})
                    current = ""
                output.append({"text": s, "kind": block["kind"], "warning": "Langer ungeteilter Satz"})
            elif len(current) + len(s) + 1 > max_chars:
                if current:
                    output.append({"text": current, "kind": block["kind"]})
                current = s
            else:
                current = (current + " " + s).strip()
        if current:
            output.append({"text": current, "kind": block["kind"]})
    return output


def load_glossary(path: Path | None = None) -> dict[str, str]:
    glossary = dict(DEFAULT_GLOSSARY)
    if path:
        custom = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(custom, dict):
            raise ValueError("Glossar muss ein JSON-Objekt sein")
        glossary.update(custom)
    return glossary
