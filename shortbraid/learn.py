"""
Failure Learning Engine.

Analyzes past session logs and tool executions, detects failed tool calls,
correlates them with successful subsequent resolutions, and generates
succinct markdown rules for CLAUDE.md / AGENTS.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional


class FailureLearner:
    """
    Learns from past errors in agent transcripts and writes guidelines to instruction files.

    Usage:
        learner = FailureLearner()
        learnings = learner.analyze_session(transcript_lines)
        learner.write_to_instructions("CLAUDE.md", learnings)
    """

    def __init__(self, target_file: Optional[str] = None):
        self.target_file = target_file or "CLAUDE.md"

    def analyze_session(self, messages_or_transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract failure-recovery pairs from a sequence of messages or transcript events."""
        learnings = []

        for i, msg in enumerate(messages_or_transcript):
            content = str(msg.get("content", ""))
            role = msg.get("role", "")

            # Check if this message indicates a tool failure
            is_failure = False
            failed_tool = ""
            error_details = ""

            if role == "tool" or msg.get("type") == "TOOL_OUTPUT":
                if any(err_kw in content.lower() for err_kw in ("error", "exception", "failed", "traceback", "command not found", "syntaxerror")):
                    is_failure = True
                    failed_tool = msg.get("name") or "tool"
                    error_details = content[:250]

            elif "tool_calls" in msg and i + 1 < len(messages_or_transcript):
                next_msg = messages_or_transcript[i + 1]
                next_content = str(next_msg.get("content", ""))
                if any(err_kw in next_content.lower() for err_kw in ("error", "exception", "failed", "exit code 1", "exit code 127")):
                    is_failure = True
                    failed_tool = msg["tool_calls"][0]["function"]["name"] if msg["tool_calls"] else "tool"
                    error_details = next_content[:250]

            if is_failure:
                # Look forward for successful resolution
                resolution = ""
                for j in range(i + 1, min(len(messages_or_transcript), i + 6)):
                    subsequent = messages_or_transcript[j]
                    sub_content = str(subsequent.get("content", ""))
                    if "passed" in sub_content.lower() or "success" in sub_content.lower() or "completed" in sub_content.lower():
                        resolution = sub_content[:250]
                        break

                rule_summary = self._synthesize_rule(failed_tool, error_details, resolution)
                learnings.append(
                    {
                        "failed_tool": failed_tool,
                        "error": error_details,
                        "resolution": resolution,
                        "rule": rule_summary,
                    }
                )

        return learnings

    def _synthesize_rule(self, tool: str, error: str, resolution: str) -> str:
        if "command not found" in error.lower():
            cmd = re.findall(r":\s*([a-zA-Z0-9_\-\.]+):\s*command not found", error)
            cmd_name = cmd[0] if cmd else "the command"
            return f"- Ensure `{cmd_name}` is installed or call via its virtualenv/full path before executing."
        if "syntaxerror" in error.lower():
            return f"- Validate script syntax and matching brackets before calling `{tool}`."
        if "permission denied" in error.lower():
            return f"- Ensure correct file permissions before invoking `{tool}`."
        return f"- When using `{tool}`, handle error pattern `{error[:60].strip()}...` by verifying preconditions."

    def write_to_instructions(
        self,
        target_path: Optional[str] = None,
        learnings: Optional[list[dict[str, Any]]] = None,
    ) -> bool:
        """Write synthesized learnings to a markdown instruction file."""
        if not learnings:
            return False

        path = Path(target_path or self.target_file)
        existing_content = path.read_text(encoding="utf-8") if path.exists() else ""

        section_header = "## Autonomous Learnings & Guidelines"
        new_rules = [f"- {item['rule']}" for item in learnings if item.get("rule")]
        new_rules_text = "\n".join(new_rules)

        if section_header in existing_content:
            updated_content = existing_content.replace(
                section_header,
                f"{section_header}\n{new_rules_text}",
            )
        else:
            updated_content = (
                existing_content.strip() + f"\n\n{section_header}\n{new_rules_text}\n"
            )

        path.write_text(updated_content, encoding="utf-8")
        return True
