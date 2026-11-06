"""CLI: python -m audiobook.cli --help."""
from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

from .pipeline import (ROOT, STOP_EVENT, approve, configure, create_book,
                       load, make_export, project_path, quality, synthesize)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokale EPUB-Hörbuchproduktion")
    sub = parser.add_subparsers(dest="action", required=True)
    imp = sub.add_parser("import", help="EPUB in einen persistenten Job übernehmen")
    imp.add_argument("epub", type=Path)
    sub.add_parser("books", help="Vorhandene Jobs auflisten")
    for command in ("chapters", "status", "preview", "approve", "run", "resume", "qa", "export", "rerender", "config"):
        cmd = sub.add_parser(command)
        cmd.add_argument("id")
        if command == "run":
            cmd.add_argument("--chapter", type=int)
        if command == "qa":
            cmd.add_argument("--asr", action="store_true")
        if command == "rerender":
            cmd.add_argument("segment")
        if command == "config":
            cmd.add_argument("--speaker")
            cmd.add_argument("--speed", type=float)
            cmd.add_argument("--glossary", type=Path)
    args = parser.parse_args()
    signal.signal(signal.SIGINT, lambda *_: STOP_EVENT.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP_EVENT.set())
    if args.action == "import":
        print(create_book(args.epub))
        return 0
    if args.action == "books":
        print(json.dumps([
            {"id": p.name, "title": json.loads((p / "manifest.json").read_text())["title"]}
            for p in ROOT.glob("*/") if (p / "manifest.json").is_file()
        ], ensure_ascii=False, indent=2))
        return 0
    if args.action == "chapters":
        result = load(args.id)["chapters"]
    elif args.action == "status":
        state = load(args.id)
        result = {k: state.get(k) for k in (
            "title", "status", "done", "total", "errors", "estimated_minutes")}
    elif args.action == "preview":
        result = synthesize(args.id, preview=True)
    elif args.action == "approve":
        result = approve(args.id)
    elif args.action in ("run", "resume"):
        result = synthesize(args.id, chapter=getattr(args, "chapter", None))
    elif args.action == "qa":
        result = quality(args.id, asr=args.asr)
    elif args.action == "export":
        result = {"m4b": str(make_export(args.id))}
    elif args.action == "rerender":
        state = load(args.id)
        segment = next((x for x in state["segments"] if x["id"] == args.segment), None)
        if segment is None:
            parser.error("Segment nicht gefunden")
        from .pipeline import _file, _signature
        _file(args.id, segment, _signature(state, segment)).unlink(missing_ok=True)
        result = synthesize(args.id, force_id=args.segment)
    else:
        current = {}
        if args.speaker:
            current["speaker"] = args.speaker
        if args.speed is not None:
            current["speed"] = args.speed
        glossary = json.loads(args.glossary.read_text(encoding="utf-8")) if args.glossary else None
        result = configure(args.id, current, glossary)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
