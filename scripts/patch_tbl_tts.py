#!/usr/bin/env python3
"""Idempotently extend the pinned TBL modal with the local Qwen3-TTS provider.

The upstream TBL repository is pinned by bootstrap.sh. This overlay only
patches its browser-side modal, leaving Edge TTS, Chatterbox and translation
backends unchanged. A missing anchor is an error rather than a silent change.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "TBL_QWEN_BRIDGE_PATCH_V1"
IMPORT_ANCHOR = "import { TTSManager } from './tts/tts-manager.js';"
MODAL_ANCHOR = "    document.body.insertAdjacentHTML('beforeend', modalHtml);"
CHANGE_ANCHOR = """        const isChatterbox = providerSelect.value === 'chatterbox';
        edgeOptions.style.display = isChatterbox ? 'none' : 'block';
        chatterboxOptions.style.display = isChatterbox ? 'block' : 'none';
        gpuStatusDiv.style.display = isChatterbox ? 'block' : 'none';"""
CLICK_ANCHOR = """        const provider = providerSelect.value;

        // Build config based on provider"""
CHANGE_REPLACEMENT = """        const isQwen = providerSelect.value === 'qwen-local';
        const isChatterbox = providerSelect.value === 'chatterbox';
        edgeOptions.style.display = (isChatterbox || isQwen) ? 'none' : 'block';
        chatterboxOptions.style.display = isChatterbox ? 'block' : 'none';
        gpuStatusDiv.style.display = isChatterbox ? 'block' : 'none';
        const qwenOptions = document.getElementById('ttsModalQwenOptions');
        if (qwenOptions) qwenOptions.style.display = isQwen ? 'block' : 'none';
        generateBtn.textContent = isQwen ? 'Sprachprobe erzeugen' : '🎧 Generate Audio';"""
CLICK_REPLACEMENT = """        const provider = providerSelect.value;
        if (provider === 'qwen-local') {
            await generateQwenFromTbl({ filename, modal, generateBtn });
            return;
        }

        // Build config based on provider"""


def replace_once(content: str, before: str, after: str) -> str:
    count = content.count(before)
    if count != 1:
        raise ValueError(f"Expected exactly one upstream TBL anchor; found {count}: {before[:72]!r}")
    return content.replace(before, after, 1)


def patch(content: str) -> tuple[str, bool]:
    if MARKER in content:
        return content, False
    content = replace_once(
        content, IMPORT_ANCHOR,
        IMPORT_ANCHOR + "\n// " + MARKER +
        "\nimport { enhanceTtsModal, generateQwenFromTbl } from '/audiobook/tbl-bridge.js';"
    )
    content = replace_once(
        content, MODAL_ANCHOR,
        MODAL_ANCHOR + "\n    enhanceTtsModal(filename, filepath);"
    )
    content = replace_once(content, CHANGE_ANCHOR, CHANGE_REPLACEMENT)
    content = replace_once(content, CLICK_ANCHOR, CLICK_REPLACEMENT)
    return content, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream_js", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="Validate the patch on disk without writing it")
    args = parser.parse_args()
    content = args.upstream_js.read_text(encoding="utf-8")
    updated, changed = patch(content)
    if not args.check and changed:
        args.upstream_js.write_text(updated, encoding="utf-8")
    print("TBL native Qwen modal " + ("patched" if changed else "already patched") +
          (" (check-only)" if args.check else ""))


if __name__ == "__main__":
    main()
