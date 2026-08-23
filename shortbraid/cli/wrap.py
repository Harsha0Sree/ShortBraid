"""
ShortBraid Wrap CLI.

Runs a command or reads stdin, compresses the output using ShortBraid's
smart engine, and emits the compressed text with token statistics.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

from shortbraid.compressor import compress


def run_wrap(args: list[str]) -> int:
    """Execute a wrapped command or compress stdin."""
    if not args or args == ["-"]:
        # Read from stdin
        raw_text = sys.stdin.read()
        if not raw_text:
            return 0
        res = compress(raw_text)
        comp_content = res.messages[0]["content"] if res.messages else ""
        sys.stdout.write(str(comp_content))
        sys.stderr.write(
            f"\n[ShortBraid] Saved {res.tokens_saved} tokens "
            f"({(1.0 - res.compression_ratio):.1%}) | {res.original_tokens} → {res.compressed_tokens}\n"
        )
        return 0

    # Run command as subprocess
    proc = subprocess.run(args, capture_output=True, text=True)
    combined = (proc.stdout or "") + (proc.stderr or "")

    res = compress(combined)
    comp_content = res.messages[0]["content"] if res.messages else ""

    sys.stdout.write(str(comp_content))
    sys.stderr.write(
        f"\n[ShortBraid] Command: {' '.join(args)} | Saved {res.tokens_saved} tokens "
        f"({(1.0 - res.compression_ratio):.1%}) | {res.original_tokens} → {res.compressed_tokens}\n"
    )
    return proc.returncode
