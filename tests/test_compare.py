"""Tests for compare.py — project comparison data gathering."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compare  # noqa: E402
import scaffold  # noqa: E402
from paths import wiki_dir  # noqa: E402


def _git_init(root):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(root),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(root),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(root),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(root),
                   check=True, capture_output=True)


def _page(type_, slug, sources=None, related_paths=None, body="", schema_version=1):
    src = f"[{', '.join(sources)}]" if sources else "[]"
    rp = f"[{', '.join(related_paths)}]" if related_paths else "[]"
    return (
        f"---\ntype: {type_}\nschema_version: {schema_version}\n"
        f"created: 2026-04-05\nupdated: 2026-04-05\nsources: {src}\n"
        f"related_paths: {rp}\n---\n# {slug}\n\n{body}\n"
    )


def _make_project(root, name, entities=None, concepts=None, patterns=None,
                  manifests=None, with_wiki=True):
    """Create a project with optional wiki + manifests."""
    _git_init(root)
    if manifests:
        for fname, content in manifests.items():
            (root / fname).write_text(content)
    (root / "README.md").write_text(f"# {name}\n")
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
        for slug in (patterns or []):
            (w / "patterns" / f"{slug}.md").write_text(_page("patterns", slug))


class TestTechStackDetection(unittest.TestCase):
    def test_node_react(self):
        manifests = {"package.json": '{"dependencies": {"react": "^18", "express": "^4"}}'}
        stack = compare.detect_tech_stack(manifests)
        self.assertIn("node", stack)
        self.assertIn("react", stack)
        self.assertIn("express", stack)

    def test_python_django(self):
        manifests = {"pyproject.toml": '[project]\ndependencies = ["django>=4"]'}
        stack = compare.detect_tech_stack(manifests)
        self.assertIn("python", stack)
        self.assertIn("django", stack)

    def test_empty_manifests(self):
        self.assertEqual(compare.detect_tech_stack({}), [])

    def test_rust_detection(self):
        manifests = {"Cargo.toml": '[package]\nname = "foo"'}
        stack = compare.detect_tech_stack(manifests)
        self.assertIn("rust", stack)


class TestReadProjectData(unittest.TestCase):
    def test_with_wiki(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_project(root, "demo", entities=["stripe"], concepts=["auth-flow"])
            data = compare.read_project_data(root, require_wiki=True)
            self.assertTrue(data["has_wiki"])
            slugs = [p["slug"] for p in data["wiki_pages"]["entities"]]
            self.assertIn("stripe", slugs)
            slugs = [p["slug"] for p in data["wiki_pages"]["concepts"]]
            self.assertIn("auth-flow", slugs)

    def test_without_wiki_no_require(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_project(root, "no-wiki", with_wiki=False)
            data = compare.read_project_data(root, require_wiki=False)
            self.assertFalse(data["has_wiki"])
            self.assertIn("README.md", data["file_tree"])

    def test_without_wiki_require_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_project(root, "no-wiki", with_wiki=False)
            with self.assertRaises(RuntimeError):
                compare.read_project_data(root, require_wiki=True)


class TestOverlap(unittest.TestCase):
    def test_shared_entities(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"
            b = Path(td) / "b"
            a.mkdir()
            b.mkdir()
            _make_project(a, "proj-a", entities=["stripe", "postgres"],
                          concepts=["auth-flow"])
            _make_project(b, "proj-b", entities=["stripe", "redis"],
                          concepts=["auth-flow", "caching"])
            result = compare.compare(a, b)
            ov = result["overlap"]
            self.assertIn("stripe", ov["entities"]["shared"])
            self.assertIn("postgres", ov["entities"]["only_current"])
            self.assertIn("redis", ov["entities"]["only_target"])
            self.assertIn("auth-flow", ov["concepts"]["shared"])
            self.assertIn("caching", ov["concepts"]["only_target"])

    def test_tech_stack_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"
            b = Path(td) / "b"
            a.mkdir()
            b.mkdir()
            _make_project(a, "proj-a",
                          manifests={"package.json": '{"dependencies":{"react":"18"}}'})
            _make_project(b, "proj-b",
                          manifests={"package.json": '{"dependencies":{"vue":"3"}}'})
            result = compare.compare(a, b)
            stack = result["overlap"]["tech_stack"]
            self.assertIn("node", stack["shared"])
            self.assertIn("react", stack["only_current"])
            self.assertIn("vue", stack["only_target"])

    def test_target_without_wiki_still_compares(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"
            b = Path(td) / "b"
            a.mkdir()
            b.mkdir()
            _make_project(a, "proj-a", entities=["stripe"])
            _make_project(b, "proj-b", with_wiki=False,
                          manifests={"package.json": '{"dependencies":{"express":"4"}}'})
            result = compare.compare(a, b)
            self.assertFalse(result["target_wiki_available"])
            self.assertIn("express", result["target"]["tech_stack"])


class TestCompareErrors(unittest.TestCase):
    def test_current_without_wiki_fails(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a"
            b = Path(td) / "b"
            a.mkdir()
            b.mkdir()
            _make_project(a, "no-wiki", with_wiki=False)
            _make_project(b, "proj-b")
            with self.assertRaises(RuntimeError):
                compare.compare(a, b)


if __name__ == "__main__":
    unittest.main()
