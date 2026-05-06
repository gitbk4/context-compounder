"""Tests for scaffold.py — mode detection + structure creation."""
import contextlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import persona_integration  # noqa: E402
import scaffold  # noqa: E402
from paths import context_root, raw_dir, schema_path, wiki_dir  # noqa: E402


@contextlib.contextmanager
def _isolated_home(home_path: Path):
    """Temporarily redirect HOME and persona_integration.PERSONA_JSON_PATH.

    Two forms are patched together: ``HOME`` env var (used by ``Path.home()``
    on POSIX) and the module-level constant (used directly by the loader).
    Restores both on exit.
    """
    old_home = os.environ.get("HOME")
    old_path = persona_integration.PERSONA_JSON_PATH
    os.environ["HOME"] = str(home_path)
    persona_integration.PERSONA_JSON_PATH = (
        home_path / ".ai-quickstart" / "persona" / "persona.json"
    )
    try:
        yield persona_integration.PERSONA_JSON_PATH
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
        persona_integration.PERSONA_JSON_PATH = old_path


def _write_persona(path: Path, paragraphs):
    path.parent.mkdir(parents=True, exist_ok=True)
    persona = {
        "schema_version": 1,
        "structured": {
            "role": "founding engineer",
            "archetype": "job",
            "industry": "developer-tools",
            "skill_tolerance": "high",
            "project_style": "ship-fast-then-rigor",
            "top_projects": [],
        },
        "paragraphs": paragraphs,
    }
    path.write_text(json.dumps(persona), encoding="utf-8")


def _snapshot_tree(root: Path) -> dict:
    """Return {relative_path: bytes} for every regular file under ``root``."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


class TestDetectMode(unittest.TestCase):
    def test_init_when_no_context_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(scaffold.detect_mode(Path(td)), "INIT")

    def test_recompile_when_context_exists(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "context").mkdir()
            self.assertEqual(scaffold.detect_mode(Path(td)), "RECOMPILE")


class TestCreateStructure(unittest.TestCase):
    """Baseline structure tests — must run with HOME isolated so the
    user's real ~/.ai-quickstart/persona/persona.json (if any) cannot
    leak in and create unexpected entities/builder.md or patterns/style.md.
    """

    def test_creates_all_dirs_and_files(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as home, \
             _isolated_home(Path(home)):
            target = Path(td)
            scaffold.create_structure(target, project_name="demo")
            self.assertTrue(context_root(target).is_dir())
            self.assertTrue(raw_dir(target).is_dir())
            self.assertTrue(wiki_dir(target).is_dir())
            for sub in ("concepts", "entities", "summaries", "patterns"):
                self.assertTrue((wiki_dir(target) / sub).is_dir())
                self.assertTrue((wiki_dir(target) / sub / ".gitkeep").exists())
            self.assertTrue(schema_path(target).is_file())
            self.assertTrue((wiki_dir(target) / "index.md").is_file())
            self.assertTrue((wiki_dir(target) / "log.md").is_file())
            self.assertTrue((wiki_dir(target) / "README.md").is_file())
            self.assertTrue((raw_dir(target) / "README.md").is_file())

    def test_refuses_to_clobber_existing_context(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "context").mkdir()
            with self.assertRaises(FileExistsError):
                scaffold.create_structure(target)

    def test_template_substitution_applied(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as home, \
             _isolated_home(Path(home)):
            target = Path(td)
            scaffold.create_structure(target, project_name="myproj")
            content = schema_path(target).read_text(encoding="utf-8")
            # Should not have raw {{ }} placeholders
            self.assertNotIn("{{project_name}}", content)
            self.assertNotIn("{{date}}", content)


class TestPersonaIntegrationInScaffold(unittest.TestCase):
    """End-to-end scaffold-with-persona tests."""

    def test_scaffold_with_persona_writes_builder_and_style(self):
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as home:
            with _isolated_home(Path(home)) as persona_path:
                _write_persona(
                    persona_path,
                    paragraphs=[
                        {"id": "p:001", "text": "stdlib only", "trust_score": 5},
                        {"id": "p:002", "text": "tests first", "trust_score": 4},
                        {"id": "p:003", "text": "low trust", "trust_score": 2},
                    ],
                )
                target = Path(td)
                scaffold.create_structure(target, project_name="demo")

                builder = wiki_dir(target) / "entities" / "builder.md"
                style = wiki_dir(target) / "patterns" / "style.md"
                self.assertTrue(builder.is_file())
                self.assertTrue(style.is_file())

                builder_text = builder.read_text(encoding="utf-8")
                self.assertIn("provenance: from-persona", builder_text)
                self.assertIn("founding engineer", builder_text)
                self.assertIn("demo", builder_text)

                style_text = style.read_text(encoding="utf-8")
                self.assertIn("> stdlib only", style_text)
                self.assertIn("> tests first", style_text)
                self.assertNotIn("low trust", style_text)

                index_text = (wiki_dir(target) / "index.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("[[builder]]", index_text)
                self.assertIn("[[style]]", index_text)

                log_text = (wiki_dir(target) / "log.md").read_text(encoding="utf-8")
                self.assertIn("persona-integration", log_text)
                self.assertIn("entities/builder.md", log_text)
                self.assertIn("patterns/style.md", log_text)

    def test_scaffold_without_persona_is_byte_identical_to_baseline(self):
        """Graceful degradation invariant: with persona absent, the entire
        context/ tree must be byte-identical to a run made without ai-quickstart
        installed at all.
        """
        with tempfile.TemporaryDirectory() as home_a, \
             tempfile.TemporaryDirectory() as home_b, \
             tempfile.TemporaryDirectory() as t1, \
             tempfile.TemporaryDirectory() as t2:
            # Baseline run: HOME points at an empty home (no persona.json).
            with _isolated_home(Path(home_a)):
                scaffold.create_structure(Path(t1), project_name="demo")
                snap_baseline = _snapshot_tree(context_root(Path(t1)))

            # Second run with persona.json deliberately removed (i.e. never
            # created). The integration must not even attempt to write the
            # new files.
            with _isolated_home(Path(home_b)) as persona_path:
                self.assertFalse(persona_path.exists())
                scaffold.create_structure(Path(t2), project_name="demo")
                snap_no_persona = _snapshot_tree(context_root(Path(t2)))

            self.assertEqual(set(snap_baseline.keys()), set(snap_no_persona.keys()))
            self.assertEqual(snap_baseline, snap_no_persona)
            # Belt-and-suspenders: the persona-only files don't exist.
            self.assertNotIn("wiki/entities/builder.md", snap_no_persona)
            self.assertNotIn("wiki/patterns/style.md", snap_no_persona)

    def test_scaffold_with_persona_but_no_high_trust_paragraphs(self):
        """With persona present but no paragraphs >= HIGH_TRUST_THRESHOLD,
        builder.md is still written (structured fields stand alone) but
        style.md is NOT written — we never write empty files. (Threshold
        is 3 as of 2026-05-06; see HIGH_TRUST_THRESHOLD docstring.)
        """
        with tempfile.TemporaryDirectory() as td, \
             tempfile.TemporaryDirectory() as home:
            with _isolated_home(Path(home)) as persona_path:
                _write_persona(
                    persona_path,
                    paragraphs=[
                        {"id": "p:001", "text": "only score 2", "trust_score": 2},
                        {"id": "p:002", "text": "only score 1", "trust_score": 1},
                    ],
                )
                target = Path(td)
                scaffold.create_structure(target, project_name="demo")

                builder = wiki_dir(target) / "entities" / "builder.md"
                style = wiki_dir(target) / "patterns" / "style.md"
                self.assertTrue(builder.is_file())
                self.assertFalse(style.exists())

                # log.md mentions builder but not style.
                log_text = (wiki_dir(target) / "log.md").read_text(encoding="utf-8")
                self.assertIn("entities/builder.md", log_text)
                self.assertNotIn("patterns/style.md", log_text)

                # index.md references builder but not style.
                index_text = (wiki_dir(target) / "index.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("[[builder]]", index_text)
                self.assertNotIn("[[style]]", index_text)


if __name__ == "__main__":
    unittest.main()
