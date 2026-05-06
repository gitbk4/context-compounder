#!/usr/bin/env python3
"""Persona-aware scaffolding integration with ai-quickstart.

Reads ``~/.ai-quickstart/persona/persona.json`` (when present) and renders
two optional wiki pages at scaffold time:

  - ``entities/builder.md`` — provenance for "who built this codebase"
  - ``patterns/style.md``   — style preferences seeded from high-trust persona prose

This module is purely additive: if persona.json is missing, malformed, or
unreadable, ``load_persona_if_available`` returns ``None`` and the caller is
expected to fall back to the existing scaffold flow with **zero observable
difference** from pre-integration behavior.

No dependency on ai-quickstart's code — persona.json is read as a plain
JSON file. Schema discipline: unknown fields are ignored; absent fields fall
back to "unspecified" sentinels.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

PERSONA_JSON_PATH = Path.home() / ".ai-quickstart" / "persona" / "persona.json"
HIGH_TRUST_THRESHOLD = 3  # paragraphs with score < 3 are excluded from style seeding
# Originally 4 per the v2-cathedral.md spec, lowered to 3 in 2026-05-06 dogfood
# follow-up: fresh-user paragraphs (heal-rewrites without anecdotes yet) score
# 3, so a 4-threshold meant style.md never seeded for new users. 3 captures
# "heal rewrote a user-typed paragraph once" — enough signal for fresh users —
# while still excluding (2) activity-inferred and (1) multi-hop content.
# See TODO-ENG-005 for raising back to 4 once anecdote-anchored paragraphs
# are common.
EXPECTED_SCHEMA_VERSION = 1
MAX_BUILDER_EXCERPTS = 3
UNSPECIFIED = "unspecified"


# ---------- loading ----------


def load_persona_if_available(
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Read persona.json. Returns ``None`` if missing, malformed, or unreadable.

    Never raises. Never blocks compathy's scaffold flow. Validates only the
    minimum: top-level is a dict, ``schema_version`` matches the version this
    module knows how to read. Any other field can be absent or unexpected
    without breaking the load.
    """
    target = Path(path) if path is not None else PERSONA_JSON_PATH
    try:
        if not target.is_file():
            return None
        text = target.read_text(encoding="utf-8")
    except OSError:
        return None
    except UnicodeDecodeError:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        return None
    return data


# ---------- helpers ----------


def _structured(persona: dict) -> dict:
    """Return the ``structured`` block as a dict (possibly empty)."""
    s = persona.get("structured")
    return s if isinstance(s, dict) else {}


def _field(persona: dict, name: str) -> str:
    """Return a structured field value or 'unspecified' fallback."""
    s = _structured(persona)
    val = s.get(name)
    if val is None or val == "":
        return UNSPECIFIED
    return str(val)


def _high_trust_paragraphs(persona: dict) -> list:
    """Return only paragraphs with trust_score >= HIGH_TRUST_THRESHOLD.

    Tolerates missing or malformed entries: anything without a numeric
    ``trust_score`` and a string ``text`` is silently dropped.
    """
    paragraphs = persona.get("paragraphs")
    if not isinstance(paragraphs, list):
        return []
    out = []
    for entry in paragraphs:
        if not isinstance(entry, dict):
            continue
        score = entry.get("trust_score")
        text = entry.get("text")
        if not isinstance(score, (int, float)):
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        if score >= HIGH_TRUST_THRESHOLD:
            out.append(text.strip())
    return out


def _today() -> str:
    return date.today().isoformat()


# ---------- rendering ----------


def render_builder_md(persona: dict, project_name: str) -> str:
    """Generate the ``entities/builder.md`` content.

    Pulls structured fields (role, archetype, project_style, skill_tolerance)
    and up to ``MAX_BUILDER_EXCERPTS`` high-trust paragraphs.
    """
    role = _field(persona, "role")
    archetype = _field(persona, "archetype")
    project_style = _field(persona, "project_style")
    skill_tolerance = _field(persona, "skill_tolerance")

    excerpts = _high_trust_paragraphs(persona)[:MAX_BUILDER_EXCERPTS]

    lines = [
        "---",
        "type: entity",
        "schema_version: 1",
        f"created: {_today()}",
        "provenance: from-persona",
        "---",
        "",
        "# Builder",
        "",
        f"This project ({project_name}) was scaffolded by:",
        "",
        f"- **Role:** {role}",
        f"- **Archetype:** {archetype}",
        f"- **Project style:** {project_style}",
        f"- **Skill tolerance:** {skill_tolerance}",
    ]
    if excerpts:
        lines.append("")
        lines.append("## Selected high-trust persona excerpts")
        lines.append("")
        for excerpt in excerpts:
            single_line = " ".join(excerpt.split())
            lines.append(f"- {single_line}")
    lines.append("")
    return "\n".join(lines)


def render_style_md(persona: dict) -> str:
    """Generate the ``patterns/style.md`` content from high-trust persona prose.

    Returns the empty string (NOT ``None``) when no qualifying paragraphs
    exist — callers decide whether to skip the file write entirely.
    """
    excerpts = _high_trust_paragraphs(persona)
    if not excerpts:
        return ""

    # NOTE: lint.py's VALID_TYPES includes "patterns" (plural). schema.md
    # documents the same plural form for the patterns/ folder. Use it here.
    lines = [
        "---",
        "type: patterns",
        "schema_version: 1",
        f"created: {_today()}",
        "provenance: from-persona",
        "---",
        "",
        "# Style preferences (seeded from persona)",
        "",
    ]
    for excerpt in excerpts:
        for paragraph_line in excerpt.splitlines():
            lines.append(f"> {paragraph_line}".rstrip())
        lines.append("")
    lines.append(
        "> Note: these patterns were seeded from the user's ai-quickstart "
        "persona at scaffold time. Edit freely — compathy will not regenerate "
        "them on subsequent runs."
    )
    lines.append("")
    return "\n".join(lines)


# ---------- index + log helpers ----------


def update_index_with_persona_pages(
    index_path: Path, *, builder: bool, style: bool
) -> None:
    """Append persona-scaffolded pages to the appropriate sections of index.md.

    Inserts ``[[builder]]`` under ``## Entities`` and ``[[style]]`` under
    ``## Patterns``, replacing the placeholder ``_(no entries yet…)_`` line
    when present so the linter's orphan check passes.
    """
    if not index_path.is_file():
        return
    text = index_path.read_text(encoding="utf-8")
    if builder:
        text = _insert_index_entry(
            text,
            section="## Entities",
            entry="- [[builder]] — who scaffolded this project (from ai-quickstart persona)",
        )
    if style:
        text = _insert_index_entry(
            text,
            section="## Patterns",
            entry="- [[style]] — style preferences seeded from ai-quickstart persona",
        )
    index_path.write_text(text, encoding="utf-8")


def _insert_index_entry(text: str, *, section: str, entry: str) -> str:
    """Insert ``entry`` directly under the heading ``section``.

    If the placeholder ``_(no entries yet…)_`` follows the heading, replace
    it with ``entry``. Otherwise append ``entry`` immediately under the
    heading. If the section is missing, leave the document unchanged.
    """
    lines = text.splitlines()
    out = []
    i = 0
    inserted = False
    while i < len(lines):
        out.append(lines[i])
        if not inserted and lines[i].strip() == section:
            # Find the first non-blank line after the heading.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                out.append(lines[j])
                j += 1
            if j < len(lines) and lines[j].lstrip().startswith("_(no entries yet"):
                # Replace the placeholder line.
                out.append(entry)
                i = j  # skip the placeholder
                inserted = True
            else:
                # Insert the entry, then continue copying.
                out.append(entry)
                i = j - 1  # back up so the loop re-handles line j next
                inserted = True
        i += 1
    if not inserted:
        return text
    # Preserve trailing newline if original had one.
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + suffix


def append_persona_log_entry(
    log_path: Path, *, builder: bool, style: bool
) -> None:
    """Append a persona-integration entry to log.md (no-op if log missing)."""
    if not log_path.is_file():
        return
    pages = []
    if builder:
        pages.append("entities/builder.md")
    if style:
        pages.append("patterns/style.md")
    if not pages:
        return
    text = log_path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    today = _today()
    text += (
        f"\n## [{today}] persona-integration | from_persona | "
        f"scaffolded {', '.join(pages)}\n"
    )
    log_path.write_text(text, encoding="utf-8")
