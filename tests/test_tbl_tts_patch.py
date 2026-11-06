"""Pinned-upstream TBL native Qwen modal integration regression tests."""
import unittest
from pathlib import Path

from scripts.patch_tbl_tts import (
    CHANGE_ANCHOR, CLICK_ANCHOR, IMPORT_ANCHOR, MODAL_ANCHOR,
    MARKER, patch,
)


class TblQwenOverlayTests(unittest.TestCase):
    def test_patch_preserves_native_providers_and_is_idempotent(self):
        original = "\n".join((
            IMPORT_ANCHOR,
            "const nativeEdge = 'edge-tts';",
            "const nativeChatterbox = 'chatterbox';",
            MODAL_ANCHOR,
            CHANGE_ANCHOR,
            CLICK_ANCHOR,
        ))
        updated, changed = patch(original)
        self.assertTrue(changed)
        self.assertIn(MARKER, updated)
        self.assertIn("enhanceTtsModal(filename, filepath);", updated)
        self.assertIn("generateQwenFromTbl({ filename, modal, generateBtn })", updated)
        self.assertIn("const nativeEdge = 'edge-tts';", updated)
        self.assertIn("const nativeChatterbox = 'chatterbox';", updated)
        second, changed_again = patch(updated)
        self.assertFalse(changed_again)
        self.assertEqual(second, updated)

    def test_mismatch_fails_loudly_and_does_not_guess(self):
        with self.assertRaisesRegex(ValueError, "Expected exactly one"):
            patch("const modalHtml = '<div>Unexpected TBL version</div>';")

    def test_adapter_is_a_separate_static_module(self):
        script = Path(__file__).resolve().parents[1] / "audiobook" / "tbl-bridge.js"
        content = script.read_text(encoding="utf-8")
        self.assertIn("export function enhanceTtsModal", content)
        self.assertIn("export async function generateQwenFromTbl", content)
        self.assertIn("preview: true", content)
        self.assertIn("'/approve'", content)
        self.assertIn("preview: false", content)
        self.assertNotIn("window.fetch =", content)


if __name__ == "__main__":
    unittest.main()
