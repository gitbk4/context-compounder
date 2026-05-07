#!/usr/bin/env python3
"""Auto-write a "Project context" section into the project's CLAUDE.md and
README.md so Claude Code (and other AI agents) discover the wiki without
having to be told.

The section is fenced by a sentinel pair (HTML comments) so re-running the
scaffold against an existing project is idempotent: existing content above
and below the sentinel pair is preserved verbatim, and only the body
between sentinels is rewritten on subsequent runs.

Public API:
    render_context_section(project_name) -> str
    upsert_section(target_path, section_body) -> str
    write_discovery_breadcrumbs(target, project_name) -> dict

Stdlib only. Never raises out of write_discovery_breadcrumbs (the caller
catches anyway, but defense in depth).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

CLAUDE_MD = "CLAUDE.md"
README_MD = "README.md"
MCP_JSON = ".mcp.json"
SENTINEL_START = "<!-- compathy:context-section START -->"
SENTINEL_END = "<!-- compathy:context-section END -->"

# Install path for the MCP server. Matches install.py's TOOL_BASES for the
# global Claude install. compathy_query.py's module docstring documents the
# same path.
COMPATHY_QUERY_PATH = (
    Path.home() / ".claude" / "skills" / "compathy" / "scripts" / "compathy_query.py"
)
COMPATHY_MCP_SERVER_KEY = "compathy-wiki"

# Files we are willing to upsert into. Other extensions (or extensionless
# binaries) are skipped defensively.
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


def render_context_section(project_name: str) -> str:
    """Return the full section body (including sentinel markers) to inject.

    The body lists key entry points (index.md, schema.md, wiki/{entities,
    concepts, patterns, summaries}, log.md) and includes a one-line note
    about the flat-YAML frontmatter convention.

    ``project_name`` is currently unused inside the section body (the body
    is project-agnostic so it can be safely upserted into any project), but
    is kept in the signature for forward compatibility — e.g. if we later
    want to mention the project by name in the heading.
    """
    # NOTE: project_name is intentionally unused right now. Keeping the
    # parameter so callers don't need to change when we start using it.
    _ = project_name
    return "\n".join(
        [
            SENTINEL_START,
            "## Project context",
            "",
            "This project has a compiled knowledge base (Karpathy-style wiki) at",
            "`context/wiki/`. Key entry points:",
            "",
            "- `context/wiki/index.md`: page directory plus cross-references",
            "- `context/schema.md`: schema version plus page-type contract",
            "- `context/wiki/entities/`: projects, people, services, vendors",
            "- `context/wiki/concepts/`: domain ideas and technical patterns",
            "- `context/wiki/patterns/`: reusable patterns and conventions",
            "- `context/wiki/summaries/`: compiled summaries of raw sources",
            "- `context/wiki/log.md`: chronological audit trail",
            "",
            "Read `index.md` first to find the right page. Pages use flat-YAML",
            "frontmatter plus markdown; compathy's `lint.py` validates the wire",
            "format.",
            SENTINEL_END,
        ]
    )


def upsert_section(target_path: Path, section_body: str) -> str:
    """Idempotent inject. Returns 'created' | 'replaced' | 'appended'.

    - If ``target_path`` does not exist, create it with ``section_body`` as
      the only content (followed by a trailing newline).
    - If it exists and contains a well-formed sentinel pair, replace
      everything between (and including) the sentinels with ``section_body``.
      Content above and below the sentinels is preserved verbatim.
    - If it exists but has no well-formed sentinel pair, append the section
      to the end (with a blank-line separator).
    - If sentinels are malformed (start without end, or end before start),
      fall back to append and emit a warning to stderr.
    """
    target_path = Path(target_path)

    if not target_path.exists():
        target_path.write_text(section_body + "\n", encoding="utf-8")
        return "created"

    existing = target_path.read_text(encoding="utf-8")
    start_idx = existing.find(SENTINEL_START)
    end_idx = existing.find(SENTINEL_END)

    has_start = start_idx != -1
    has_end = end_idx != -1
    well_formed = has_start and has_end and end_idx > start_idx

    if well_formed:
        # Replace the block, preserving everything before SENTINEL_START
        # and everything after SENTINEL_END.
        before = existing[:start_idx]
        after = existing[end_idx + len(SENTINEL_END):]
        new_text = before + section_body + after
        target_path.write_text(new_text, encoding="utf-8")
        return "replaced"

    if has_start or has_end:
        # Malformed: only one sentinel present, or end before start.
        # Append a fresh section and warn so the user can clean up.
        print(
            f"[compathy/discovery] warning: malformed sentinel pair in "
            f"{target_path}; appending a new section instead of replacing.",
            file=sys.stderr,
        )

    # No sentinels (or malformed): append.
    separator = "" if existing.endswith("\n\n") else (
        "\n" if existing.endswith("\n") else "\n\n"
    )
    new_text = existing + separator + section_body + "\n"
    target_path.write_text(new_text, encoding="utf-8")
    return "appended"


def render_mcp_entry(target: Path) -> Dict[str, Any]:
    """Return the dict for the 'compathy-wiki' MCP server entry.

    The ``--target`` arg is substituted with the absolute project path at
    write time so strict ``.mcp.json`` parsers don't need env var expansion.
    Stdio transport, no env vars, no auth.
    """
    return {
        "command": "python3",
        "args": [str(COMPATHY_QUERY_PATH), "--target", str(Path(target).resolve())],
        "transport": "stdio",
    }


def upsert_mcp_json(target: Path) -> str:
    """Idempotent inject of the compathy-wiki entry into ``<target>/.mcp.json``.

    Returns one of:
      * ``'created'`` if no .mcp.json existed before.
      * ``'added'`` if the file existed but had no compathy-wiki entry.
      * ``'replaced'`` if the file existed with a prior compathy-wiki entry.
      * ``'skipped-malformed'`` if the existing .mcp.json couldn't be parsed
        as JSON, in which case the file is NOT modified (defense in depth).

    Other ``mcpServers`` entries are preserved untouched. The contract: we
    only mutate ``mcpServers.compathy-wiki``.
    """
    target = Path(target)
    path = target / MCP_JSON
    entry = render_mcp_entry(target)

    if not path.exists():
        payload = {"mcpServers": {COMPATHY_MCP_SERVER_KEY: entry}}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return "created"

    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(
            f"[compathy/discovery] warning: malformed or unreadable {path}: {e}; "
            f"leaving file unchanged.",
            file=sys.stderr,
        )
        return "skipped-malformed"

    if not isinstance(existing, dict):
        print(
            f"[compathy/discovery] warning: {path} root is not a JSON object; "
            f"leaving file unchanged.",
            file=sys.stderr,
        )
        return "skipped-malformed"

    servers = existing.get("mcpServers")
    had_prior = isinstance(servers, dict) and COMPATHY_MCP_SERVER_KEY in servers
    if not isinstance(servers, dict):
        existing["mcpServers"] = {COMPATHY_MCP_SERVER_KEY: entry}
        status = "added"
    else:
        status = "replaced" if had_prior else "added"
        servers[COMPATHY_MCP_SERVER_KEY] = entry

    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return status


def write_discovery_breadcrumbs(target: Path, project_name: str) -> Dict[str, str]:
    """Write CLAUDE.md, README.md, and .mcp.json breadcrumbs at project root.

    Returns a dict with keys 'claude_md', 'readme_md', and 'mcp_json'. Markdown
    statuses are 'created' | 'replaced' | 'appended' | 'skipped'. The
    ``mcp_json`` status is 'created' | 'added' | 'replaced' |
    'skipped-malformed' | 'error'.

    Files with non-markdown suffixes are skipped (defense in depth: both
    files are markdown by convention, but if a user has a binary CLAUDE.md
    for some reason, we won't damage it).
    """
    target = Path(target)
    section_body = render_context_section(project_name)
    result: Dict[str, str] = {
        "claude_md": "skipped",
        "readme_md": "skipped",
        "mcp_json": "skipped",
    }

    for key, name in (("claude_md", CLAUDE_MD), ("readme_md", README_MD)):
        path = target / name
        # Both filenames end in .md, but if the file already exists with a
        # weird suffix because someone symlinked it, _markdown_ok returns
        # False and we skip. For the canonical names CLAUDE.md / README.md,
        # this always passes.
        if not _markdown_ok(path):
            result[key] = "skipped"
            continue
        try:
            result[key] = upsert_section(path, section_body)
        except OSError as e:
            print(
                f"[compathy/discovery] warning: failed to write {path}: {e}",
                file=sys.stderr,
            )
            result[key] = "skipped"

    try:
        result["mcp_json"] = upsert_mcp_json(target)
    except OSError as e:
        print(
            f"[compathy/discovery] warning: failed to write .mcp.json: {e}",
            file=sys.stderr,
        )
        result["mcp_json"] = "error"

    return result


def _markdown_ok(path: Path) -> bool:
    """Return True if ``path`` looks safe to upsert markdown into.

    We accept anything with a markdown-ish suffix. The canonical names
    CLAUDE.md and README.md always pass.
    """
    suffix = path.suffix.lower()
    return suffix in _MARKDOWN_SUFFIXES
