#!/usr/bin/env python3
"""Migrate a project's ruff configuration to extend a consensus ruff.toml.

This script vendors a consensus ruff.toml into a project's .skeleton/ directory
and rewrites the project's pyproject.toml [tool.ruff] sections to use
``extend = ".skeleton/ruff.toml"`` with only project-local overrides.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tomllib
from pathlib import Path

try:
    import tomli_w
except ImportError:
    print("Error: tomli_w is required. Install with: pip install tomli_w", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Consensus config parsing (T010)
# ---------------------------------------------------------------------------

def parse_consensus(path: Path) -> dict:
    """Parse the consensus ruff.toml into a structured dict."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    result = {}
    if "line-length" in data:
        result["line-length"] = data["line-length"]

    lint = data.get("lint", {})
    if "extend-select" in lint:
        result["extend-select"] = set(lint["extend-select"])
    if "ignore" in lint:
        result["ignore"] = set(lint["ignore"])
    if "extend-per-file-ignores" in lint:
        # Convert to frozenset-of-tuples for comparison
        result["extend-per-file-ignores"] = {
            k: set(v) for k, v in lint["extend-per-file-ignores"].items()
        }

    if "flake8-quotes" in lint:
        result["flake8-quotes"] = lint["flake8-quotes"]

    fmt = data.get("format", {})
    if fmt:
        result["format"] = fmt

    return result


# ---------------------------------------------------------------------------
# Project config parsing (T011)
# ---------------------------------------------------------------------------

def parse_project(project_path: Path) -> tuple[dict, dict, bool]:
    """Parse the project's ruff config from pyproject.toml (and ruff.toml if present).

    Returns (ruff_config, full_pyproject, has_standalone_ruff_toml).

    ruff_config is a nested dict mirroring [tool.ruff] structure.
    """
    pyproject_path = project_path / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"Error: {pyproject_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)

    ruff_config = pyproject.get("tool", {}).get("ruff", {})

    # Check for standalone ruff.toml
    standalone_path = project_path / "ruff.toml"
    has_standalone = standalone_path.exists()

    if has_standalone:
        with open(standalone_path, "rb") as f:
            standalone = tomllib.load(f)
        # Merge standalone into ruff_config (standalone takes precedence for
        # top-level keys; nested dicts are merged)
        ruff_config = _deep_merge(ruff_config, standalone)

    return ruff_config, pyproject, has_standalone


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, returning a new dict. Override wins on conflicts."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Extract project's extend-select/ignore as sets (handling nested lint section)
# ---------------------------------------------------------------------------

def _get_lint(config: dict) -> dict:
    """Get lint settings, handling both flat and nested structures."""
    return config.get("lint", {})


def _get_project_extend_select(config: dict) -> set[str]:
    lint = _get_lint(config)
    return set(lint.get("extend-select", []))


def _get_project_ignore(config: dict) -> set[str]:
    lint = _get_lint(config)
    return set(lint.get("ignore", []))


def _get_project_per_file_ignores(config: dict) -> dict[str, set[str]]:
    """Get all per-file-ignores, merging both per-file-ignores and extend-per-file-ignores."""
    lint = _get_lint(config)
    result: dict[str, set[str]] = {}
    # Collect from per-file-ignores (non-extend, replaces)
    for k, v in lint.get("per-file-ignores", {}).items():
        result.setdefault(k, set()).update(v)
    # Collect from extend-per-file-ignores (additive)
    for k, v in lint.get("extend-per-file-ignores", {}).items():
        result.setdefault(k, set()).update(v)
    return result


# ---------------------------------------------------------------------------
# Diff-based override computation (T012)
# ---------------------------------------------------------------------------

def compute_overrides(project_config: dict, consensus: dict) -> dict:
    """Compute project-local overrides that differ from consensus.

    Returns a ruff config dict containing only project-specific settings.
    """
    overrides: dict = {}

    # --- extend-select ---
    proj_select = _get_project_extend_select(project_config)
    cons_select = consensus.get("extend-select", set())
    local_select = proj_select - cons_select
    if local_select:
        overrides.setdefault("lint", {})["extend-select"] = sorted(local_select)

    # --- ignore ---
    proj_ignore = _get_project_ignore(project_config)
    cons_ignore = consensus.get("ignore", set())
    local_ignore = proj_ignore - cons_ignore
    if local_ignore:
        overrides.setdefault("lint", {})["ignore"] = sorted(local_ignore)

    # --- extend-per-file-ignores ---
    # NOTE: ruff resolves per-file-ignore globs relative to the config file's
    # directory.  Since the consensus ruff.toml lives in .skeleton/, its
    # extend-per-file-ignores patterns will resolve against .skeleton/ and
    # never match project source files.  We must therefore always include ALL
    # per-file-ignores (both project-local and consensus) in the project's
    # own pyproject.toml so they resolve against the project root.
    proj_pfi = _get_project_per_file_ignores(project_config)
    cons_pfi = consensus.get("extend-per-file-ignores", {})
    merged_pfi: dict[str, list[str]] = {}
    # Start with all consensus per-file-ignores (must be in project config)
    for pattern, rules in cons_pfi.items():
        merged_pfi[pattern] = sorted(rules)
    # Layer project-specific per-file-ignores on top
    for pattern, rules in proj_pfi.items():
        if pattern in merged_pfi:
            merged_pfi[pattern] = sorted(set(merged_pfi[pattern]) | rules)
        else:
            merged_pfi[pattern] = sorted(rules)
    if merged_pfi:
        overrides.setdefault("lint", {})["extend-per-file-ignores"] = merged_pfi

    # --- All other settings: keep if not in consensus or differs ---
    proj_lint = _get_lint(project_config)

    # Lint sub-tables (flake8-quotes, isort, etc.)
    handled_lint_keys = {"extend-select", "ignore", "per-file-ignores", "extend-per-file-ignores"}
    for key, value in proj_lint.items():
        if key in handled_lint_keys:
            continue
        # Compare with consensus lint-level settings
        if key == "flake8-quotes":
            if value != consensus.get("flake8-quotes", {}):
                overrides.setdefault("lint", {})[key] = value
        else:
            # Keep all other lint sub-settings (isort, per-file-ignores, etc.)
            overrides.setdefault("lint", {})[key] = value

    # Top-level ruff settings
    handled_top_keys = {"lint", "format"}
    for key, value in project_config.items():
        if key in handled_top_keys:
            continue
        if key == "line-length":
            if value != consensus.get("line-length"):
                overrides[key] = value
        else:
            # Keep all other top-level settings (extend-exclude, target-version, etc.)
            overrides[key] = value

    # Format settings
    proj_format = project_config.get("format", {})
    cons_format = consensus.get("format", {})
    if proj_format and proj_format != cons_format:
        overrides["format"] = proj_format

    return overrides


# ---------------------------------------------------------------------------
# Additive compensation (T013)
# ---------------------------------------------------------------------------

def compute_compensation_ignores(
    project_config: dict, consensus: dict
) -> list[str]:
    """Compute compensation ignores for consensus rules not in original project.

    Since extend-select is additive via ruff's ``extend``, any rule group in
    the consensus that was NOT in the project's original config would introduce
    new violations.  We compensate by adding those groups to the project's
    ignore list.
    """
    proj_select = _get_project_extend_select(project_config)
    cons_select = consensus.get("extend-select", set())

    # Rule groups in consensus but NOT in project's original config
    newly_inherited = cons_select - proj_select
    return sorted(newly_inherited)


# ---------------------------------------------------------------------------
# File operations (T014)
# ---------------------------------------------------------------------------

def perform_migration(
    project_path: Path,
    consensus_path: Path,
    consensus: dict,
    project_config: dict,
    pyproject: dict,
    has_standalone: bool,
    dry_run: bool,
    verbose: bool,
) -> dict:
    """Perform the migration and return a summary dict."""
    overrides = compute_overrides(project_config, consensus)
    compensation = compute_compensation_ignores(project_config, consensus)

    # Merge compensation ignores into overrides
    if compensation:
        lint_overrides = overrides.setdefault("lint", {})
        existing_ignore = list(lint_overrides.get("ignore", []))
        merged = sorted(set(existing_ignore) | set(compensation))
        lint_overrides["ignore"] = merged

    # Build the new [tool.ruff] section
    new_ruff: dict = {"extend": ".skeleton/ruff.toml"}
    # Add overrides in a sensible order
    for key in ("line-length", "target-version", "extend-exclude", "exclude"):
        if key in overrides:
            new_ruff[key] = overrides.pop(key)

    # Remaining top-level overrides (except lint, format)
    for key in sorted(overrides.keys()):
        if key not in ("lint", "format"):
            new_ruff[key] = overrides.pop(key)

    if "lint" in overrides:
        new_ruff["lint"] = overrides["lint"]
    if "format" in overrides:
        new_ruff["format"] = overrides["format"]

    # Build the new pyproject content
    new_pyproject = dict(pyproject)
    if "tool" not in new_pyproject:
        new_pyproject["tool"] = {}
    new_pyproject["tool"]["ruff"] = new_ruff

    skeleton_dir = project_path / ".skeleton"
    vendored_path = skeleton_dir / "ruff.toml"

    summary = {
        "vendored_path": str(vendored_path),
        "modified_files": [],
        "removed_files": [],
        "overrides": overrides,
        "compensation_ignores": compensation,
    }

    if dry_run:
        print("=== DRY RUN ===")
        print()
        print(f"Would create directory: {skeleton_dir}")
        print(f"Would copy {consensus_path} -> {vendored_path}")
        print(f"Would rewrite: {project_path / 'pyproject.toml'}")
        if has_standalone:
            print(f"Would remove: {project_path / 'ruff.toml'}")
        print()
        print("New [tool.ruff] content:")
        print("---")
        print(tomli_w.dumps({"tool": {"ruff": new_ruff}}))
        print("---")
        return summary

    # Create .skeleton/ directory
    skeleton_dir.mkdir(exist_ok=True)
    summary["modified_files"].append(str(vendored_path))

    # Copy consensus ruff.toml (preserving comments)
    shutil.copy2(consensus_path, vendored_path)

    # Rewrite pyproject.toml
    pyproject_path = project_path / "pyproject.toml"
    with open(pyproject_path, "wb") as f:
        tomli_w.dump(new_pyproject, f)
    summary["modified_files"].append(str(pyproject_path))

    # Remove standalone ruff.toml if it existed
    if has_standalone:
        standalone = project_path / "ruff.toml"
        standalone.unlink()
        summary["removed_files"].append(str(standalone))

    if verbose:
        print(f"Created {vendored_path}")
        print(f"Rewrote {pyproject_path}")
        if has_standalone:
            print(f"Removed {project_path / 'ruff.toml'}")

    return summary


# ---------------------------------------------------------------------------
# Summary output (T015)
# ---------------------------------------------------------------------------

def print_summary(summary: dict) -> None:
    """Print a human-readable migration summary."""
    print()
    print("=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print()
    print(f"  Vendored consensus config: {summary['vendored_path']}")
    print()

    if summary["modified_files"]:
        print("  Modified files:")
        for f in summary["modified_files"]:
            print(f"    - {f}")
    if summary["removed_files"]:
        print("  Removed files:")
        for f in summary["removed_files"]:
            print(f"    - {f}")

    print()

    overrides = summary.get("overrides", {})
    if overrides:
        print("  Project-local overrides:")
        lint = overrides.get("lint", {})
        if "extend-select" in lint:
            print(f"    extend-select: {lint['extend-select']}")
        if "ignore" in lint:
            # Separate compensation from project-local
            comp = set(summary.get("compensation_ignores", []))
            proj_ignore = [r for r in lint["ignore"] if r not in comp]
            if proj_ignore:
                print(f"    ignore (project-local): {proj_ignore}")
        if "extend-per-file-ignores" in lint:
            print(f"    extend-per-file-ignores: {lint['extend-per-file-ignores']}")
        for key in sorted(lint.keys()):
            if key not in ("extend-select", "ignore", "extend-per-file-ignores"):
                print(f"    lint.{key}: {lint[key]}")
        for key in sorted(overrides.keys()):
            if key != "lint":
                print(f"    {key}: {overrides[key]}")
    else:
        print("  Project-local overrides: (none)")

    compensation = summary.get("compensation_ignores", [])
    if compensation:
        print()
        print(f"  Compensation ignores (newly inherited from consensus):")
        print(f"    {compensation}")
    else:
        print()
        print("  Compensation ignores: (none)")

    print()
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI (T009)
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate a project's ruff config to extend a consensus ruff.toml.",
    )
    parser.add_argument(
        "project_path",
        type=Path,
        help="Path to the project directory containing pyproject.toml",
    )
    parser.add_argument(
        "--consensus",
        type=Path,
        default=None,
        help="Path to the consensus ruff.toml (default: ruff.toml next to this script)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing any files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress information",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_path = args.project_path.resolve()
    if not project_path.is_dir():
        print(f"Error: {project_path} is not a directory", file=sys.stderr)
        return 1

    # Resolve consensus path
    if args.consensus is not None:
        consensus_path = args.consensus.resolve()
    else:
        consensus_path = (Path(__file__).resolve().parent / "ruff.toml")

    if not consensus_path.exists():
        print(f"Error: consensus config not found at {consensus_path}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Project path: {project_path}")
        print(f"Consensus config: {consensus_path}")

    # Parse configs
    consensus = parse_consensus(consensus_path)
    project_config, pyproject, has_standalone = parse_project(project_path)

    if args.verbose:
        proj_select = _get_project_extend_select(project_config)
        cons_select = consensus.get("extend-select", set())
        print(f"Project extend-select: {sorted(proj_select)}")
        print(f"Consensus extend-select: {sorted(cons_select)}")
        print(f"Project-only rules: {sorted(proj_select - cons_select)}")
        print(f"Newly inherited from consensus: {sorted(cons_select - proj_select)}")

    # Perform migration
    summary = perform_migration(
        project_path=project_path,
        consensus_path=consensus_path,
        consensus=consensus,
        project_config=project_config,
        pyproject=pyproject,
        has_standalone=has_standalone,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
