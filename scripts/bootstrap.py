#!/usr/bin/env python3
"""Emit compile hints from the target project: git log, file tree, READMEs, manifests.

Claude reads this JSON to produce an initial wiki on first-run, even when raw/ is empty.
Caps apply to keep the output bounded.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

GIT_LOG_LIMIT = 100
TREE_DEPTH = 3
README_MAX_CHARS = 10_000
MANIFEST_MAX_CHARS = 10_000
MANIFEST_NAMES = (
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "CMakeLists.txt",
    "Makefile",
)
README_CANDIDATES = ("README.md", "README.rst", "README.txt", "readme.md", "README")
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}


def _run_git(args, cwd: Path):
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        raise RuntimeError("git not found on PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git {args[0]} timed out")


def is_git_repo(root: Path) -> bool:
    try:
        r = _run_git(["rev-parse", "--show-toplevel"], root)
        return r.returncode == 0
    except RuntimeError:
        return False


def collect_git_log(root: Path, limit: int = GIT_LOG_LIMIT) -> list:
    if not is_git_repo(root):
        return []
    r = _run_git(
        ["log", f"-{limit}", "--pretty=format:%h %ad %s", "--date=short"], root
    )
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def collect_file_tree(root: Path, max_depth: int = TREE_DEPTH) -> list:
    if is_git_repo(root):
        r = _run_git(["ls-files"], root)
        if r.returncode == 0:
            files = [
                f
                for f in r.stdout.splitlines()
                if f.strip() and f.count("/") < max_depth
            ]
            return sorted(files)
    # Fallback: filesystem walk with manual ignores
    results = []
    for p in Path(root).rglob("*"):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if any(part in IGNORE_DIRS or part.startswith(".") for part in parts):
            continue
        if len(parts) > max_depth:
            continue
        if p.is_file():
            results.append(str(rel))
    return sorted(results)


def _read_truncated(p: Path, cap: int) -> str:
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(content) > cap:
        content = content[:cap] + "\n... [truncated]"
    return content


def collect_readmes(root: Path) -> list:
    seen = set()
    results = []
    for name in README_CANDIDATES:
        p = root / name
        if p.is_file() and p.name.lower() not in seen:
            seen.add(p.name.lower())
            results.append(
                {
                    "path": str(p.relative_to(root)),
                    "content": _read_truncated(p, README_MAX_CHARS),
                }
            )
    return results


def collect_manifests(root: Path) -> dict:
    out = {}
    for name in MANIFEST_NAMES:
        p = root / name
        if p.is_file():
            out[name] = _read_truncated(p, MANIFEST_MAX_CHARS)
    return out


def emit_bootstrap(root: Path) -> dict:
    return {
        "is_git_repo": is_git_repo(root),
        "git_log": collect_git_log(root),
        "file_tree": collect_file_tree(root),
        "readmes": collect_readmes(root),
        "manifests": collect_manifests(root),
        "caps": {
            "git_log_limit": GIT_LOG_LIMIT,
            "tree_depth": TREE_DEPTH,
            "readme_max_chars": README_MAX_CHARS,
            "manifest_max_chars": MANIFEST_MAX_CHARS,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".", help="project root (default: cwd)")
    args = ap.parse_args()
    root = Path(args.target).resolve()

    try:
        data = emit_bootstrap(root)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
