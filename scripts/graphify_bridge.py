#!/usr/bin/env python3
"""Check graphify availability, run it on large codebases, and emit structured JSON.

Outputs a JSON object to stdout describing whether graphify was used and what it found.
Always exits 0 — never blocks the compathy skill.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb",
    ".java", ".kt", ".swift", ".cpp", ".c", ".cs", ".php",
}
CODE_FILE_THRESHOLD = 50
GRAPHIFY_TIMEOUT = 90
GOD_NODE_LIMIT = 15


def _skip(reason: str) -> dict:
    return {"used": False, "reason": reason}


def _count_code_files(root: Path) -> int:
    try:
        r = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if r.returncode == 0:
            return sum(
                1 for f in r.stdout.splitlines()
                if Path(f).suffix.lower() in CODE_EXTENSIONS
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return sum(1 for p in root.rglob("*") if p.is_file() and p.suffix.lower() in CODE_EXTENSIONS)


def _run_graphify(root: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["graphify", ".", "--output-dir", "graphify-out/"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=GRAPHIFY_TIMEOUT,
            check=False,
        )
        if r.returncode != 0:
            return False, (r.stderr or r.stdout)[:200]
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"timed out after {GRAPHIFY_TIMEOUT}s"
    except FileNotFoundError:
        return False, "graphify executable not found at runtime"


def _parse_graph(root: Path) -> dict:
    graph_path = root / "graphify-out" / "graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))

    nodes = {n["id"]: n.get("label", n["id"]) for n in data.get("nodes", [])}
    links = data.get("links", data.get("edges", []))

    degree: dict[str, int] = defaultdict(int)
    file_edges: dict[str, list[str]] = defaultdict(list)

    for link in links:
        src_id = link.get("source")
        tgt_id = link.get("target")
        degree[src_id] += 1
        degree[tgt_id] += 1

        if link.get("relation") in ("calls", "imports"):
            src_file = link.get("source_file", "")
            tgt_file = link.get("target_file", link.get("source_file", ""))
            if src_file and tgt_file and src_file != tgt_file:
                if (root / src_file).exists():
                    file_edges[src_file].append(tgt_file)

    god_nodes = [
        nodes[nid]
        for nid, _ in sorted(degree.items(), key=lambda x: -x[1])[:GOD_NODE_LIMIT]
        if nid in nodes
    ]

    raw_hyperedges = data.get("graph", {}).get("hyperedges", [])
    communities = [
        [nodes.get(nid, nid) for nid in he]
        for he in raw_hyperedges
        if isinstance(he, list)
    ]

    deduped_edges = {src: list(dict.fromkeys(tgts)) for src, tgts in file_edges.items()}

    return {"god_nodes": god_nodes, "communities": communities, "file_edges": deduped_edges}


def run(target: Path) -> dict:
    if not shutil.which("graphify"):
        return _skip("graphify not installed")

    code_count = _count_code_files(target)
    if code_count < CODE_FILE_THRESHOLD:
        return _skip(f"{code_count} code files < threshold ({CODE_FILE_THRESHOLD})")

    ok, err = _run_graphify(target)
    if not ok:
        return _skip(f"graphify run failed: {err}")

    report_src = target / "graphify-out" / "GRAPH_REPORT.md"
    report_dst = target / "context" / "raw" / "graphify-report.md"
    if report_src.exists() and report_dst.parent.exists():
        shutil.copy2(report_src, report_dst)

    try:
        graph_data = _parse_graph(target)
    except Exception as exc:
        return _skip(f"graphify parse failed: {type(exc).__name__}: {exc}")

    return {
        "used": True,
        "reason": f"{code_count} code files >= threshold ({CODE_FILE_THRESHOLD})",
        **graph_data,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".", help="project root (default: cwd)")
    args = ap.parse_args()
    root = Path(args.target).resolve()
    print(json.dumps(run(root), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
