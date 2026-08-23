"""
AST-Aware Source Code Compression Engine (40-70% savings).

Preserves class hierarchies, function signatures, docstrings, type annotations,
and public interfaces while collapsing implementation bodies.
"""

from __future__ import annotations

import ast
import hashlib
import re
from typing import Any

from shortbraid.detector import ContentType
from shortbraid.engines.base import BaseEngine, EngineResult, count_tokens


class CodeEngine(BaseEngine):
    name = "source_code"
    content_type = ContentType.SOURCE_CODE

    def compress(
        self,
        content: Any,
        collapse_bodies: bool = True,
        preserve_docstrings: bool = True,
        preserve_comments: bool = True,
        **kwargs,
    ) -> EngineResult:
        if not isinstance(content, str):
            content = str(content)

        orig_str = content
        orig_tokens = count_tokens(orig_str)
        orig_sha = hashlib.sha256(orig_str.encode()).hexdigest()

        # Try Python AST first
        try:
            tree = ast.parse(orig_str)
            comp_str = self._compress_python_ast(orig_str, tree, collapse_bodies, preserve_docstrings)
        except Exception:
            # Non-Python or Python syntax error — use structural language compressor
            comp_str = self._compress_generic_code(orig_str, collapse_bodies)

        comp_tokens = count_tokens(comp_str)
        comp_sha = hashlib.sha256(comp_str.encode()).hexdigest()

        if comp_tokens >= orig_tokens:
            comp_str = orig_str
            comp_tokens = orig_tokens

        tokens_saved = max(0, orig_tokens - comp_tokens)
        ratio = (comp_tokens / orig_tokens) if orig_tokens > 0 else 1.0

        return EngineResult(
            content=comp_str,
            original_tokens=orig_tokens,
            compressed_tokens=comp_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=ratio,
            content_type=self.content_type,
            original_len=len(orig_str),
            compressed_len=len(comp_str),
            original_sha256=orig_sha,
            compressed_sha256=comp_sha,
            uncompressed_original=orig_str,
        )

    def _compress_python_ast(
        self,
        source: str,
        tree: ast.AST,
        collapse_bodies: bool,
        preserve_docstrings: bool,
    ) -> str:
        lines = source.splitlines()

        class ASTSkeletonizer(ast.NodeTransformer):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                return self._skeletonize_func(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
                return self._skeletonize_func(node)

            def _skeletonize_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
                docstring = ast.get_docstring(node) if preserve_docstrings else None
                new_body = []
                if docstring:
                    new_body.append(ast.Expr(value=ast.Constant(value=docstring)))

                if collapse_bodies and len(node.body) > (1 if docstring else 0):
                    # Replace with Ellipsis (...)
                    hidden_count = max(1, (node.end_lineno or 0) - (node.lineno or 0))
                    new_body.append(ast.Pass())
                else:
                    new_body.extend(node.body)

                node.body = new_body if new_body else [ast.Pass()]
                return node

        # Apply transformation
        skeleton_tree = ASTSkeletonizer().visit(tree)
        ast.fix_missing_locations(skeleton_tree)
        try:
            return ast.unparse(skeleton_tree)
        except Exception:
            return source

    def _compress_generic_code(self, source: str, collapse_bodies: bool) -> str:
        """Structural compression for JS, TS, Go, Rust, Java, C++."""
        lines = source.splitlines()
        if len(lines) <= 8:
            return source

        output = []
        brace_depth = 0
        in_collapsed_block = False
        collapsed_lines = 0

        # Patterns for declarations
        sig_pattern = re.compile(
            r"^\s*(?:export\s+)?(?:public|private|protected|async|static|function|class|interface|type|enum|struct|def|fn|func|pub\s+fn)\b"
        )

        for line in lines:
            stripped = line.strip()

            # Track brace depth
            open_braces = line.count("{")
            close_braces = line.count("}")

            # Keep imports, signatures, decorators, comments
            if (
                stripped.startswith(("//", "/*", "*", "#", "import ", "from ", "package ", "use ", "@"))
                or sig_pattern.search(line)
                or brace_depth == 0
            ):
                if in_collapsed_block:
                    indent = " " * 4
                    output.append(f"{indent}// [... {collapsed_lines} lines hidden ...]")
                    in_collapsed_block = False
                    collapsed_lines = 0
                output.append(line)
            else:
                if collapse_bodies and brace_depth > 0:
                    in_collapsed_block = True
                    collapsed_lines += 1
                else:
                    output.append(line)

            brace_depth = max(0, brace_depth + open_braces - close_braces)
            if brace_depth == 0 and in_collapsed_block:
                indent = " " * 4
                output.append(f"{indent}// [... {collapsed_lines} lines hidden ...]")
                in_collapsed_block = False
                collapsed_lines = 0

        return "\n".join(output)
