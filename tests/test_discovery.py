"""Tests for discovery.py — sentinel-fenced upsert into CLAUDE.md / README.md."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import discovery  # noqa: E402


class TestRenderContextSection(unittest.TestCase):
    def test_includes_both_sentinels(self):
        body = discovery.render_context_section("demo")
        self.assertIn(discovery.SENTINEL_START, body)
        self.assertIn(discovery.SENTINEL_END, body)
        # START must precede END.
        self.assertLess(
            body.index(discovery.SENTINEL_START),
            body.index(discovery.SENTINEL_END),
        )

    def test_lists_key_entry_points(self):
        body = discovery.render_context_section("demo")
        self.assertIn("context/wiki/index.md", body)
        self.assertIn("context/schema.md", body)
        self.assertIn("context/wiki/entities/", body)
        self.assertIn("context/wiki/concepts/", body)
        self.assertIn("context/wiki/patterns/", body)
        self.assertIn("context/wiki/summaries/", body)
        self.assertIn("context/wiki/log.md", body)
        self.assertIn("flat-YAML", body)

    def test_no_em_dashes(self):
        body = discovery.render_context_section("demo")
        # Repo convention: no em-dashes anywhere.
        self.assertNotIn("—", body)


class TestUpsertSection(unittest.TestCase):
    def test_creates_file_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "CLAUDE.md"
            body = discovery.render_context_section("demo")
            status = discovery.upsert_section(path, body)
            self.assertEqual(status, "created")
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn(discovery.SENTINEL_START, text)
            self.assertIn(discovery.SENTINEL_END, text)

    def test_appends_when_no_sentinels(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "CLAUDE.md"
            existing = "# My project\n\nSome existing notes.\n"
            path.write_text(existing, encoding="utf-8")
            body = discovery.render_context_section("demo")
            status = discovery.upsert_section(path, body)
            self.assertEqual(status, "appended")
            text = path.read_text(encoding="utf-8")
            # Existing content preserved at the top.
            self.assertTrue(text.startswith("# My project"))
            self.assertIn("Some existing notes.", text)
            # New section appended.
            self.assertIn(discovery.SENTINEL_START, text)
            self.assertIn(discovery.SENTINEL_END, text)

    def test_replaces_when_well_formed_sentinels(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "CLAUDE.md"
            before = "# My project\n\nIntro paragraph.\n\n"
            after = "\n\n## Other section\n\nKept verbatim.\n"
            old_body = (
                discovery.SENTINEL_START
                + "\n## Project context\n\nstale body\n"
                + discovery.SENTINEL_END
            )
            path.write_text(before + old_body + after, encoding="utf-8")

            new_body = discovery.render_context_section("demo")
            status = discovery.upsert_section(path, new_body)
            self.assertEqual(status, "replaced")

            text = path.read_text(encoding="utf-8")
            # Surrounding content preserved verbatim.
            self.assertTrue(text.startswith(before))
            self.assertTrue(text.endswith(after))
            # Stale body is gone, new body is present.
            self.assertNotIn("stale body", text)
            self.assertIn("Karpathy-style wiki", text)

    def test_round_trip_no_duplicate_sections(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "CLAUDE.md"
            body = discovery.render_context_section("demo")
            discovery.upsert_section(path, body)
            first = path.read_text(encoding="utf-8")
            discovery.upsert_section(path, body)
            second = path.read_text(encoding="utf-8")
            self.assertEqual(first, second)
            # And only one sentinel pair in the file.
            self.assertEqual(second.count(discovery.SENTINEL_START), 1)
            self.assertEqual(second.count(discovery.SENTINEL_END), 1)

    def test_malformed_sentinels_falls_back_to_append(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "CLAUDE.md"
            existing = (
                "# My project\n\n"
                + discovery.SENTINEL_START
                + "\n## stale, no end sentinel\n"
            )
            path.write_text(existing, encoding="utf-8")
            body = discovery.render_context_section("demo")
            status = discovery.upsert_section(path, body)
            self.assertEqual(status, "appended")
            text = path.read_text(encoding="utf-8")
            # Original malformed section still there (we don't touch it).
            self.assertIn("stale, no end sentinel", text)
            # Our new section is present too (with both sentinels).
            self.assertIn(discovery.SENTINEL_END, text)
            # SENTINEL_START appears twice now (the malformed one + ours).
            self.assertEqual(text.count(discovery.SENTINEL_START), 2)
            # SENTINEL_END appears exactly once (only ours).
            self.assertEqual(text.count(discovery.SENTINEL_END), 1)


class TestWriteDiscoveryBreadcrumbs(unittest.TestCase):
    def test_happy_path_creates_both_files(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            result = discovery.write_discovery_breadcrumbs(target, "demo")
            self.assertEqual(result, {"claude_md": "created", "readme_md": "created"})
            self.assertTrue((target / "CLAUDE.md").is_file())
            self.assertTrue((target / "README.md").is_file())
            # Both contain the sentinel pair.
            for fname in ("CLAUDE.md", "README.md"):
                text = (target / fname).read_text(encoding="utf-8")
                self.assertIn(discovery.SENTINEL_START, text)
                self.assertIn(discovery.SENTINEL_END, text)

    def test_existing_claude_md_replaced_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            preface = "# My project\n\nUser-written notes above the section.\n\n"
            old_body = (
                discovery.SENTINEL_START
                + "\nstale section body\n"
                + discovery.SENTINEL_END
                + "\n"
            )
            tail = "\n## User-written tail\n\nKept verbatim.\n"
            (target / "CLAUDE.md").write_text(preface + old_body + tail, encoding="utf-8")
            # README.md does not exist yet.
            result = discovery.write_discovery_breadcrumbs(target, "demo")
            self.assertEqual(result["claude_md"], "replaced")
            self.assertEqual(result["readme_md"], "created")

            claude_text = (target / "CLAUDE.md").read_text(encoding="utf-8")
            # User content above and below preserved.
            self.assertTrue(claude_text.startswith(preface))
            self.assertTrue(claude_text.endswith(tail))
            # Stale body gone.
            self.assertNotIn("stale section body", claude_text)
            # New body present.
            self.assertIn("Karpathy-style wiki", claude_text)

    def test_pre_existing_content_above_and_below_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            preface = (
                "# My project\n\n"
                "## Setup\n\n"
                "Run `make install`.\n\n"
            )
            old_body = (
                discovery.SENTINEL_START
                + "\n## Project context\n\nstale\n"
                + discovery.SENTINEL_END
            )
            tail = "\n\n## License\n\nMIT.\n"
            (target / "CLAUDE.md").write_text(
                preface + old_body + tail, encoding="utf-8"
            )

            result = discovery.write_discovery_breadcrumbs(target, "demo")
            self.assertEqual(result["claude_md"], "replaced")

            text = (target / "CLAUDE.md").read_text(encoding="utf-8")
            # Verbatim above.
            self.assertIn("Run `make install`.", text)
            self.assertTrue(text.startswith(preface))
            # Verbatim below.
            self.assertIn("MIT.", text)
            self.assertTrue(text.endswith(tail))

    def test_returns_status_dict_shape(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            # README.md exists without sentinels; CLAUDE.md does not exist.
            (target / "README.md").write_text("# Existing readme\n", encoding="utf-8")
            result = discovery.write_discovery_breadcrumbs(target, "demo")
            self.assertEqual(set(result.keys()), {"claude_md", "readme_md"})
            self.assertEqual(result["claude_md"], "created")
            self.assertEqual(result["readme_md"], "appended")


if __name__ == "__main__":
    unittest.main()
