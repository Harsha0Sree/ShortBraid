"""
ShortBraid Main CLI Entrypoint.
"""

from __future__ import annotations

import sys
import click

import shortbraid
from shortbraid.cli.learn import run_learn
from shortbraid.cli.mcp import run_mcp_stdio
from shortbraid.cli.perf import run_benchmarks
from shortbraid.cli.proxy import run_proxy
from shortbraid.cli.wrap import run_wrap


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(shortbraid.__version__, "-v", "--version", message="ShortBraid version %(version)s")
def cli():
    """ShortBraid — Production-grade LLM Context Compression, Retrieval & Memory Platform."""
    pass


@cli.command("proxy")
@click.option("--host", default="0.0.0.0", help="Host interface to bind on (default: 0.0.0.0)")
@click.option("--port", default=8000, type=int, help="Port to bind on (default: 8000)")
@click.option("--upstream", default="", help="Upstream LLM provider base URL")
def proxy_command(host: str, port: int, upstream: str):
    """Run the transparent reverse proxy for OpenAI / Anthropic / LiteLLM."""
    run_proxy(host=host, port=port, upstream=upstream)


@cli.command("wrap", context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.pass_context
def wrap_command(ctx):
    """Wrap a command or process to compress its output before LLM consumption."""
    args = ctx.args
    exit_code = run_wrap(args)
    if exit_code != 0:
        sys.exit(exit_code)


@cli.command("mcp")
def mcp_command():
    """Start the Model Context Protocol (MCP) server over stdio for Claude Desktop / Cursor."""
    run_mcp_stdio()


@cli.command("learn")
@click.option("--source", default=".", help="Directory or JSON/JSONL transcript file to analyze")
@click.option("--output", default="CLAUDE.md", help="Target markdown instruction file to update")
def learn_command(source: str, output: str):
    """Extract failure learnings from session transcripts and write rules to CLAUDE.md."""
    run_learn(source_path=source, output_file=output)


@cli.command("perf")
def perf_command():
    """Run real-world performance benchmarks across logs, JSON arrays, code, diffs, and text."""
    run_benchmarks()


def main():
    cli()


if __name__ == "__main__":
    main()
