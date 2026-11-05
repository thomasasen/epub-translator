#!/usr/bin/env python3
"""Probe NVIDIA VRAM on RunPod with retries and actionable diagnostics.

Print only the largest single GPU's VRAM (MiB) to stdout on success.
Failures go to stderr; never guess VRAM or silently fall back to CPU.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time

QUERY = ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]


def parse_vram(output: str) -> list[int]:
    """Accept both numeric CSV and 'NNNN MiB' output; ignore headers and N/A."""
    values = []
    for line in output.splitlines():
        match = re.fullmatch(r"\s*(\d+)\s*(?:MiB)?\s*", line, flags=re.I)
        if match:
            value = int(match.group(1))
            if value > 0:
                values.append(value)
    return values


def run_smi(command: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", "nvidia-smi not found in the container"
    except subprocess.TimeoutExpired:
        return 124, "", f"nvidia-smi timed out after {timeout}s"
    except OSError as exc:
        return 1, "", f"Failed to execute nvidia-smi: {exc}"


def probe(attempts: int, delay: float) -> int:
    last = (1, "", "not yet attempted")
    for i in range(1, attempts + 1):
        last = run_smi(QUERY)
        code, stdout, stderr = last
        sizes = parse_vram(stdout) if code == 0 else []
        if sizes:
            print(max(sizes))
            if i > 1:
                print(f"GPU detected on probe {i}/{attempts}.", file=sys.stderr)
            return 0
        print(f"GPU probe {i}/{attempts} did not return usable VRAM "
              f"(nvidia-smi exit={code}); retrying if time remains.", file=sys.stderr, flush=True)
        if i < attempts:
            time.sleep(delay)

    code, out, err = last
    _, list_out, list_err = run_smi(["nvidia-smi", "-L"])
    print("\nGPU PROBE FAILED: RunPod GPU is unavailable or nvidia-smi cannot report VRAM.",
          file=sys.stderr)
    print(f"Last query exit code: {code}", file=sys.stderr)
    print(f"Last query stdout: {out or '<empty>'}", file=sys.stderr)
    print(f"Last query stderr: {err or '<empty>'}", file=sys.stderr)
    print(f"nvidia-smi -L: {list_out or list_err or '<empty>'}", file=sys.stderr)
    devices = glob.glob("/dev/nvidia*")
    print(f"Visible NVIDIA devices: {', '.join(devices) if devices else '<none>'}",
          file=sys.stderr)
    for key in ("NVIDIA_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES"):
        print(f"{key}={os.environ.get(key, '<not set>')}", file=sys.stderr)
    print("Check the Pod's assigned GPU count in RunPod. An image's CUDA banner "
          "does not indicate that a GPU is allocated. If the Pod has zero GPUs, "
          "deploy a GPU Pod or attach an available GPU. If a GPU is assigned but "
          "not visible, check RunPod host/driver availability or contact RunPod support.",
          file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--delay", type=float, default=5.0)
    args = parser.parse_args()
    if args.attempts < 1 or args.attempts > 120 or args.delay < 0 or args.delay > 60:
        parser.error("attempts must be 1..120 and delay must be 0..60")
    return probe(args.attempts, args.delay)


if __name__ == "__main__":
    sys.exit(main())
