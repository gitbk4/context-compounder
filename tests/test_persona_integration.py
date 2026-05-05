"""Tests for persona_integration.py — load + render contracts."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import persona_integration  # noqa: E402


def _full_persona():
    return {
        "schema_version": 1,
        "generated_at": "2026-05-01T12:00:00Z",
        "from_md_sha": "abc123",
        "structured": {
            "role": "founding engineer",
            "archetype": "job",
            "industry": "developer-tools",
            "skill_tolerance": "high",
            "project_style": "ship-fast-then-rigor",
            "top_projects": [{"name": "compathy", "scaffolded_at": "2026-04-01"}],
        },
        "paragraphs": [
            {
                "id": "p:001",
                "text": "Prefers stdlib-only Python with explicit error handling.",
                "provenance": "pinned",
                "trust_score": 5,
                "anchored_to": None,
                "locked": True,
            },
            {
                "id": "p:002",
                "text": "Writes tests before shipping; tolerates manual QA only behind a flag.",
                "provenance": "anecdote",
                "trust_score": 4,
                "anchored_to": "anec-42",
                "locked": False,
            },
            {
                "id": "p:003",
                "text": "Prefers shorter functions, even at the cost of one extra indirection.",
                "provenance": "heal",
                "trust_score": 3,
                "anchored_to": "anec-9",
                "locked": False,
            },
            {
                "id": "p:004",
                "text": "Inferred preference for monorepo layouts.",
                "provenance": "activity-inferred",
                "trust_score": 2,
                "anchored_to": None,
                "locked": False,
            },
        ],
    }


def _sparse_persona():
    return {
        "schema_version": 1,
        "structured": {
            "role": None,
            "archetype": "exploring",
            "industry": None,
            "skill_tolerance": None,
            "project_style": None,
            "top_projects": [],
        },
        "paragraphs": [],
    }


class TestLoadPersonaIfAvailable(unittest.TestCase):
    def test_returns_dict_when_file_present_and_valid(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "persona.json"
            p.write_text(json.dumps(_full_persona()), encoding="utf-8")
            result = persona_integration.load_persona_if_available(p)
            self.assertIsInstance(result, dict)
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["structured"]["role"], "founding engineer")

    def test_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "nope.json"
            self.assertIsNone(persona_integration.load_persona_if_available(p))

    def test_returns_none_when_malformed_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "persona.json"
            p.write_text("{ this is not json", encoding="utf-8")
            self.assertIsNone(persona_integration.load_persona_if_available(p))

    def test_returns_none_when_wrong_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "persona.json"
            p.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            self.assertIsNone(persona_integration.load_persona_if_available(p))

    def test_returns_none_when_top_level_not_dict(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "persona.json"
            p.write_text(json.dumps(["a", "b"]), encoding="utf-8")
            self.assertIsNone(persona_integration.load_persona_if_available(p))

    def test_uses_default_path_when_none_passed(self):
        # Just check that calling with no args doesn't raise — return value
        # depends on whether the user's actual persona.json is present.
        result = persona_integration.load_persona_if_available()
        self.assertIn(type(result).__name__, ("dict", "NoneType"))


class TestRenderBuilderMd(unittest.TestCase):
    def test_full_persona_includes_all_structured_fields(self):
        md = persona_integration.render_builder_md(_full_persona(), "myproj")
        self.assertIn("type: entity", md)
        self.assertIn("provenance: from-persona", md)
        self.assertIn("# Builder", md)
        self.assertIn("myproj", md)
        self.assertIn("founding engineer", md)
        self.assertIn("job", md)
        self.assertIn("ship-fast-then-rigor", md)
        self.assertIn("high", md)
        # High-trust excerpts (score >= 4) included; lower ones excluded.
        self.assertIn("stdlib-only Python", md)
        self.assertIn("Writes tests before shipping", md)
        self.assertNotIn("monorepo layouts", md)

    def test_sparse_persona_uses_unspecified_fallbacks(self):
        md = persona_integration.render_builder_md(_sparse_persona(), "demo")
        self.assertIn("# Builder", md)
        self.assertIn("Role:** unspecified", md)
        # archetype is the only field actually set
        self.assertIn("Archetype:** exploring", md)
        self.assertIn("Project style:** unspecified", md)
        self.assertIn("Skill tolerance:** unspecified", md)
        # No "Selected high-trust" section when there are no qualifying excerpts
        self.assertNotIn("Selected high-trust", md)

    def test_caps_excerpts_at_three(self):
        persona = _full_persona()
        # Add four more high-trust paragraphs => 6 total, but builder caps at 3
        persona["paragraphs"].extend(
            [
                {"id": f"p:0{i}", "text": f"excerpt {i}", "trust_score": 5}
                for i in range(5, 9)
            ]
        )
        md = persona_integration.render_builder_md(persona, "demo")
        self.assertEqual(md.count("\n- "), 4 + 3)  # 4 structured bullets + 3 excerpts


class TestRenderStyleMd(unittest.TestCase):
    def test_high_trust_paragraphs_render_as_quotes(self):
        md = persona_integration.render_style_md(_full_persona())
        self.assertNotEqual(md, "")
        self.assertIn("type: patterns", md)
        self.assertIn("provenance: from-persona", md)
        self.assertIn("# Style preferences", md)
        # Both score-5 and score-4 paragraphs included
        self.assertIn("> Prefers stdlib-only Python", md)
        self.assertIn("> Writes tests before shipping", md)
        # Score-3 and score-2 paragraphs excluded
        self.assertNotIn("shorter functions", md)
        self.assertNotIn("monorepo layouts", md)
        # Footer note present
        self.assertIn("Edit freely", md)

    def test_returns_empty_string_when_no_high_trust_paragraphs(self):
        persona = {
            "schema_version": 1,
            "paragraphs": [
                {"id": "p:001", "text": "low trust", "trust_score": 2},
                {"id": "p:002", "text": "also low", "trust_score": 3},
            ],
        }
        self.assertEqual(persona_integration.render_style_md(persona), "")

    def test_returns_empty_string_when_no_paragraphs_field(self):
        self.assertEqual(persona_integration.render_style_md({"schema_version": 1}), "")

    def test_tolerates_malformed_paragraph_entries(self):
        persona = {
            "schema_version": 1,
            "paragraphs": [
                "not a dict",
                {"id": "p:001"},  # no text, no score
                {"id": "p:002", "text": "valid", "trust_score": 5},
                {"id": "p:003", "text": "", "trust_score": 5},  # empty text
                {"id": "p:004", "text": "no score field"},
            ],
        }
        md = persona_integration.render_style_md(persona)
        self.assertIn("> valid", md)


if __name__ == "__main__":
    unittest.main()
