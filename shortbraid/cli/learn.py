"""
ShortBraid Learn CLI.

Extracts failure learnings from session transcripts and writes them to instruction files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from shortbraid.learn import FailureLearner


def run_learn(source_path: str = ".", output_file: str = "CLAUDE.md") -> None:
    """Analyze sessions and write learnings."""
    src = Path(source_path)
    learner = FailureLearner(target_file=output_file)
    all_events: list[dict] = []

    if src.is_file():
        if src.suffix == ".jsonl":
            for line in src.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        all_events.append(json.loads(line))
                    except Exception:
                        pass
        elif src.suffix == ".json":
            try:
                data = json.loads(src.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    all_events.extend(data)
                elif isinstance(data, dict) and "messages" in data:
                    all_events.extend(data["messages"])
            except Exception:
                pass
    elif src.is_dir():
        # Scan for transcript logs
        for jsonl_file in src.glob("**/*.jsonl"):
            for line in jsonl_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip():
                    try:
                        all_events.append(json.loads(line))
                    except Exception:
                        pass

    learnings = learner.analyze_session(all_events)
    if learnings:
        learner.write_to_instructions(output_file, learnings)
        print(f"✅ Discovered {len(learnings)} new failure learnings and wrote them to {output_file}")
        for l in learnings:
            print(f"  {l['rule']}")
    else:
        print("ℹ️ No failure patterns identified in the provided sessions.")
