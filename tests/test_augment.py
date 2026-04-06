"""Tests for augment.py — target analysis for augmentation."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import augment  # noqa: E402
import scaffold  # noqa: E402
from paths import raw_dir, wiki_dir  # noqa: E402


def _git_init(root):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(root),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(root),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(root),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(root),
                   check=True, capture_output=True)


def _page(type_, slug, schema_version=1):
    return (
        f"---\ntype: {type_}\nschema_version: {schema_version}\n"
        f"created: 2026-04-05\nupdated: 2026-04-05\nsources: []\n---\n"
        f"# {slug}\n\nContent.\n"
    )


def _make_project(root, name, entities=None, concepts=None, with_wiki=True,
                  manifests=None):
    _git_init(root)
    (root / "README.md").write_text(f"# {name}\n")
    if manifests:
        for fname, content in manifests.items():
            (root / fname).write_text(content)
    subprocess.run(["git", "add", "."], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(root),
                   check=True, capture_output=True)
    if with_wiki:
        scaffold.create_structure(root, project_name=name)
        w = wiki_dir(root)
        for slug in (entities or []):
            (w / "entities" / f"{slug}.md").write_text(_page("entity", slug))
        for slug in (concepts or []):
            (w / "concepts" / f"{slug}.md").write_text(_page("concept", slug))


class TestAnalyzeTarget(unittest.TestCase):
    def test_target_with_wiki(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "current"
            target = Path(td) / "target"
            current.mkdir()
            target.mkdir()
            _make_project(current, "my-project", entities=["api"])
            _make_project(target, "admired", entities=["stripe", "plaid"],
                          concepts=["error-handling"])
            result = augment.analyze_target(current, target)
            self.assertTrue(result["target_wiki_available"])
            slugs = [p["slug"] for p in result["target"]["wiki_pages"]["entities"]]
            self.assertIn("stripe", slugs)
            self.assertIn("plaid", slugs)
            self.assertEqual(result["current_project_name"], "current")
            self.assertEqual(result["current_page_count"], 1)  # just "api"

    def test_target_without_wiki(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "current"
            target = Path(td) / "target"
            current.mkdir()
            target.mkdir()
            _make_project(current, "my-project", entities=["api"])
            _make_project(target, "no-wiki", with_wiki=False,
                          manifests={"package.json": '{"name":"no-wiki"}'})
            result = augment.analyze_target(current, target)
            self.assertFalse(result["target_wiki_available"])
            self.assertIn("node", result["target"]["tech_stack"])

    def test_current_without_wiki_fails(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "current"
            target = Path(td) / "target"
            current.mkdir()
            target.mkdir()
            _make_project(current, "no-wiki", with_wiki=False)
            _make_project(target, "good")
            with self.assertRaises(RuntimeError):
                augment.analyze_target(current, target)


class TestAugmentDir(unittest.TestCase):
    def test_path_construction(self):
        root = Path("/fake/project")
        result = augment.augment_dir(root, "stripe-node")
        self.assertEqual(result, Path("/fake/project/context/raw/augmented/stripe-node"))


class TestExistingAugments(unittest.TestCase):
    def test_detects_previous_augments(self):
        with tempfile.TemporaryDirectory() as td:
            current = Path(td) / "current"
            target = Path(td) / "target"
            current.mkdir()
            target.mkdir()
            _make_project(current, "my-project", entities=["api"])
            _make_project(target, "admired")
            # Simulate a previous augment — dir name matches target dir name, not project name
            aug = raw_dir(current.resolve()) / "augmented" / "target"
            aug.mkdir(parents=True)
            (aug / "error-handling.md").write_text("# Error Handling\n")
            result = augment.analyze_target(current, target)
            self.assertIn("error-handling.md", result["existing_augments"])


if __name__ == "__main__":
    unittest.main()
