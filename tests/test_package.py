"""
Tests for package metadata, public exports, CLI entrypoints, and typing compliance.
"""

from pathlib import Path
import re
import shortbraid
from click.testing import CliRunner
from shortbraid.cli.main import cli, main
from shortbraid.engines import ENGINE_REGISTRY


def test_package_version():
    """Verify package version is defined and follows semantic versioning."""
    assert hasattr(shortbraid, "__version__")
    assert isinstance(shortbraid.__version__, str)
    # Check valid SemVer format (e.g. 0.2.0)
    assert re.match(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9_\-\.]*)?$", shortbraid.__version__)


def test_package_all_exports():
    """Verify all symbols listed in __all__ exist and are importable."""
    assert hasattr(shortbraid, "__all__")
    assert isinstance(shortbraid.__all__, list)
    assert len(shortbraid.__all__) > 0

    for export_name in shortbraid.__all__:
        assert hasattr(shortbraid, export_name), f"Export '{export_name}' missing from shortbraid module"
        attr = getattr(shortbraid, export_name)
        assert attr is not None, f"Export '{export_name}' is None"


def test_py_typed_exists():
    """Verify PEP 561 py.typed marker file exists in package root."""
    package_dir = Path(shortbraid.__file__).parent
    py_typed = package_dir / "py.typed"
    assert py_typed.exists(), "py.typed marker file is missing from shortbraid package root"


def test_engine_registry():
    """Verify all standard compression engines are properly registered."""
    for content_type in shortbraid.ContentType:
        assert content_type in ENGINE_REGISTRY, f"ContentType '{content_type}' not in ENGINE_REGISTRY"
        engine = ENGINE_REGISTRY[content_type]
        assert isinstance(engine, shortbraid.BaseEngine)


def test_cli_version_flag():
    """Verify shortbraid CLI --version outputs correct version string."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert shortbraid.__version__ in result.output
    assert "ShortBraid version" in result.output


def test_cli_help_flag():
    """Verify shortbraid CLI --help displays help description and subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "ShortBraid" in result.output
    assert "proxy" in result.output
    assert "wrap" in result.output
    assert "mcp" in result.output
    assert "learn" in result.output
    assert "perf" in result.output


def test_main_function_callable():
    """Verify main entrypoint is callable."""
    assert callable(main)
