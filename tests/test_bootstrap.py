"""Tests for bootstrap.py — git log + file tree + readmes + manifests."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap  # noqa: E402


def _git(args, cwd):
    subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )


def _init_repo(root: Path):
    _git(["init", "-q", "-b", "main"], root)
    _git(["config", "user.email", "t@t.com"], root)
    _git(["config", "user.name", "t"], root)
    _git(["config", "commit.gpgsign", "false"], root)


class TestBootstrap(unittest.TestCase):
    def test_no_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertFalse(bootstrap.is_git_repo(root))
            data = bootstrap.emit_bootstrap(root)
            self.assertFalse(data["is_git_repo"])
            self.assertEqual(data["git_log"], [])

    def test_git_log_and_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            (root / "README.md").write_text("# Demo\n")
            (root / "main.py").write_text("print('x')\n")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("x = 1\n")
            _git(["add", "."], root)
            _git(["commit", "-q", "-m", "initial"], root)

            self.assertTrue(bootstrap.is_git_repo(root))
            data = bootstrap.emit_bootstrap(root)
            self.assertTrue(data["is_git_repo"])
            self.assertEqual(len(data["git_log"]), 1)
            self.assertIn("initial", data["git_log"][0])
            self.assertIn("README.md", data["file_tree"])
            self.assertIn("src/app.py", data["file_tree"])

    def test_readmes_collected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# Hi\n")
            data = bootstrap.emit_bootstrap(root)
            self.assertEqual(len(data["readmes"]), 1)
            self.assertIn("Hi", data["readmes"][0]["content"])

    def test_readme_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("x" * (bootstrap.README_MAX_CHARS + 100))
            data = bootstrap.emit_bootstrap(root)
            self.assertIn("[truncated]", data["readmes"][0]["content"])

    def test_manifests_collected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text('{"name": "x"}')
            (root / "pyproject.toml").write_text('[project]\nname = "x"\n')
            data = bootstrap.emit_bootstrap(root)
            self.assertIn("package.json", data["manifests"])
            self.assertIn("pyproject.toml", data["manifests"])

    def test_tree_filesystem_fallback(self):
        """Without a git repo, walks filesystem with ignores."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.md").write_text("a")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "junk.js").write_text("x")
            tree = bootstrap.collect_file_tree(root)
            self.assertIn("a.md", tree)
            self.assertNotIn("node_modules/junk.js", tree)


if __name__ == "__main__":
    unittest.main()
