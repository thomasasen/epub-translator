"""GPU detection tests, without NVIDIA hardware."""
import contextlib
import io
import unittest
from unittest.mock import patch

from scripts import probe_gpu


class ProbeTests(unittest.TestCase):
    def test_numeric_and_mib_values(self):
        self.assertEqual(probe_gpu.parse_vram("49140\n24564\n"), [49140, 24564])
        self.assertEqual(probe_gpu.parse_vram("memory.total [MiB]\n49140 MiB\n"), [49140])
        self.assertEqual(probe_gpu.parse_vram("N/A\nNo devices were found\n"), [])

    def test_delayed_gpu_becomes_available(self):
        with patch.object(probe_gpu, "run_smi", side_effect=[
            (1, "", "Failed to initialize NVML"),
            (0, "49140", ""),
        ]), patch.object(probe_gpu.time, "sleep") as sleeper:
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = probe_gpu.probe(2, 0)
            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue(), "49140\n")
            self.assertIn("probe 2/2", stderr.getvalue())
            sleeper.assert_called_once_with(0)

    def test_multiple_gpus_uses_single_largest(self):
        with patch.object(probe_gpu, "run_smi", return_value=(0, "24564\n49140", "")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(probe_gpu.probe(1, 0), 0)
            self.assertEqual(output.getvalue(), "49140\n")

    def test_missing_gpu_fails_with_diagnostics(self):
        with patch.object(probe_gpu, "run_smi", side_effect=[
            (1, "", "No devices were found"),
            (1, "", "No devices were found"),
        ]), patch.object(probe_gpu.glob, "glob", return_value=[]):
            stderr, stdout = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                status = probe_gpu.probe(1, 0)
            self.assertEqual(status, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("No devices were found", stderr.getvalue())
            self.assertIn("assigned GPU count", stderr.getvalue())
            self.assertIn("<none>", stderr.getvalue())

    def test_unreadable_gpu_memory_does_not_fabricate_amount(self):
        with patch.object(probe_gpu, "run_smi", side_effect=[
            (0, "N/A", ""),
            (0, "GPU 0: Example GPU", ""),
        ]), patch.object(probe_gpu.glob, "glob", return_value=["/dev/nvidia0"]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                status = probe_gpu.probe(1, 0)
            self.assertEqual(status, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("N/A", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
