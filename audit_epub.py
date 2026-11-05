#!/usr/bin/env python3
"""Offline structural EPUB quality audit. No model/API required; source files stay local.

This cannot assess semantic fidelity or German literary quality. It detects common
formatting failures, dropped sections, blank/unchanged paragraphs and broken EPUBs.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "o": "http://www.idpf.org/2007/opf",
}
BLOCK = {"p", "li", "blockquote", "td", "th"} | {"h" + str(i) for i in range(1, 7)}
WHITESPACE = re.compile(r"\s+")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def normalize(text: str) -> str:
    return WHITESPACE.sub(" ", text).strip()


def parse_epub(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        invalid = archive.testzip()
        if invalid is not None:
            raise ValueError(f"Corrupt ZIP entry: {invalid}")
        try:
            container = ET.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//c:rootfile", NS)
            if rootfile is None:
                raise ValueError("Missing OPF rootfile")
            opf_path = rootfile.attrib["full-path"]
            package = ET.fromstring(archive.read(opf_path))
        except (KeyError, ET.ParseError) as exc:
            raise ValueError(f"Invalid EPUB metadata: {exc}") from exc

        manifest = {}
        for item in package.findall(".//o:manifest/o:item", NS):
            identifier = item.attrib.get("id")
            href = unquote(item.attrib.get("href", "").split("#", 1)[0])
            location = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
            if identifier:
                manifest[identifier] = {"file": location, "type": item.attrib.get("media-type", "")}
        spine = package.find(".//o:spine", NS)
        if spine is None:
            raise ValueError("Missing OPF spine")
        chapters = []
        for itemref in spine.findall("o:itemref", NS):
            identifier = itemref.attrib.get("idref")
            if identifier not in manifest:
                raise ValueError(f"Spine refers to missing manifest item: {identifier}")
            entry = manifest[identifier]
            if entry["type"] not in {"application/xhtml+xml", "text/html"}:
                continue
            try:
                raw = archive.read(entry["file"])
                root = ET.fromstring(raw)
            except (KeyError, ET.ParseError) as exc:
                raise ValueError(f"Invalid XHTML in {entry['file']}: {exc}") from exc
            blocks = []
            counts = Counter()
            anchor_ids = set()
            hrefs = []
            for elem in root.iter():
                name = local_name(elem.tag)
                counts[name] += 1
                if elem.attrib.get("id"):
                    anchor_ids.add(elem.attrib["id"])
                if name == "a" and elem.attrib.get("href"):
                    hrefs.append(elem.attrib["href"])
                if name in BLOCK:
                    text = normalize("".join(elem.itertext()))
                    if text:
                        blocks.append(text)
            chapter_text = normalize(" ".join(root.itertext()))
            chapters.append({
                "file": entry["file"],
                "characters": len(chapter_text),
                "blocks": blocks,
                "counts": counts,
                "ids": anchor_ids,
                "hrefs": hrefs,
            })
        if not chapters:
            raise ValueError("EPUB spine contains no XHTML chapters")
        images = sum(1 for entry in manifest.values() if entry["type"].startswith("image/"))
        return {"chapters": chapters, "images": images}


def audit(source: Path, translated: Path) -> dict:
    result = {"source": str(source), "translated": str(translated),
              "critical": [], "warnings": [], "chapter_stats": []}
    try:
        original, output = parse_epub(source), parse_epub(translated)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        result["critical"].append(f"Cannot validate EPUB structure: {exc}")
        return result

    src_ch = original["chapters"]
    dst_ch = output["chapters"]
    if len(src_ch) != len(dst_ch):
        result["critical"].append(
            f"Spine chapter count differs: source={len(src_ch)}, translation={len(dst_ch)}")
    if original["images"] != output["images"]:
        result["warnings"].append(
            f"Embedded image count differs: {original['images']} -> {output['images']}")
    for i, (src, dst) in enumerate(zip(src_ch, dst_ch), 1):
        if src["characters"] > 100 and dst["characters"] == 0:
            result["critical"].append(f"Chapter {i}: translated chapter is empty")
        if src["characters"] > 200:
            ratio = dst["characters"] / src["characters"]
            if ratio < .55 or ratio > 2.1:
                result["warnings"].append(
                    f"Chapter {i}: suspicious character-length ratio {ratio:.2f} "
                    f"({src['characters']} -> {dst['characters']}); manually verify")
        else:
            ratio = None
        for kind in ("p", "li", "blockquote", "td", "th", "a", "img", "image", "sup"):
            if src["counts"][kind] != dst["counts"][kind]:
                result["warnings"].append(
                    f"Chapter {i}: <{kind}> element count differs: "
                    f"{src['counts'][kind]} -> {dst['counts'][kind]}")
        heading_src = sum(src["counts"][f"h{k}"] for k in range(1, 7))
        heading_dst = sum(dst["counts"][f"h{k}"] for k in range(1, 7))
        if heading_src != heading_dst:
            result["warnings"].append(
                f"Chapter {i}: heading count differs: {heading_src} -> {heading_dst}")
        if src["ids"] - dst["ids"]:
            result["warnings"].append(
                f"Chapter {i}: {len(src['ids'] - dst['ids'])} original anchor IDs missing")
        if len(src["hrefs"]) != len(dst["hrefs"]):
            result["warnings"].append(
                f"Chapter {i}: hyperlink count differs: {len(src['hrefs'])} -> {len(dst['hrefs'])}")
        # Exact matches of long source paragraphs indicate likely untranslated text.
        remaining = Counter(block for block in dst["blocks"] if len(block) >= 80)
        identical = 0
        for block in src["blocks"]:
            if len(block) >= 80 and remaining[block]:
                identical += 1
                remaining[block] -= 1
        if identical:
            result["warnings"].append(
                f"Chapter {i}: {identical} long text block(s) unchanged; check for untranslated passages")
        result["chapter_stats"].append({
            "chapter": i,
            "source_file": src["file"],
            "translated_file": dst["file"],
            "source_characters": src["characters"],
            "translated_characters": dst["characters"],
            "ratio": round(ratio, 3) if ratio is not None else None,
            "source_blocks": len(src["blocks"]),
            "translated_blocks": len(dst["blocks"]),
        })
    result["ok"] = not result["critical"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original EPUB")
    parser.add_argument("translated", type=Path, help="Translated EPUB")
    parser.add_argument("--json", dest="json_path", type=Path, help="Write machine-readable report")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero for any warning")
    args = parser.parse_args()
    report = audit(args.source, args.translated)
    print(f"EPUB audit: {len(report['critical'])} critical, {len(report['warnings'])} warnings")
    for level in ("critical", "warnings"):
        for item in report[level]:
            print(f"  {level.upper()}: {item}")
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {args.json_path}")
    if report["critical"] or (args.strict and report["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
