"""Tests for graphify_bridge.py — optional graphify integration layer."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import graphify_bridge  # noqa: E402


def _ls_files_result(n: int, ext: str = ".py") -> MagicMock:
    """Return a mock subprocess result with n tracked code files."""
    m = MagicMock()
    m.returncode = 0
    m.stdout = "\n".join(f"src/file_{i}{ext}" for i in range(n))
    return m


def _graphify_result(returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = ""
    m.stderr = ""
    return m


def _subprocess_dispatch(ls_result, graphify_result):
    """Return a side_effect fn that routes git vs graphify subprocess calls."""
    def _run(cmd, **kwargs):
        if isinstance(cmd, list) and "ls-files" in cmd:
            return ls_result
        return graphify_result
    return _run


class TestGraphifyBridge(unittest.TestCase):

    # ------------------------------------------------------------------
    # Case 1: graphify not on PATH
    # ------------------------------------------------------------------

    def test_not_installed(self):
        with patch("graphify_bridge.shutil.which", return_value=None):
            result = graphify_bridge.run(Path("."))
        self.assertFalse(result["used"])
        self.assertIn("not installed", result["reason"])

    def test_not_installed_json_only(self):
        """Only 'used' and 'reason' keys present when graphify is absent."""
        with patch("graphify_bridge.shutil.which", return_value=None):
            result = graphify_bridge.run(Path("."))
        self.assertEqual(set(result.keys()), {"used", "reason"})

    # ------------------------------------------------------------------
    # Case 2: below threshold
    # ------------------------------------------------------------------

    def test_below_threshold(self):
        with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
             patch("graphify_bridge.subprocess.run",
                   side_effect=_subprocess_dispatch(_ls_files_result(30), _graphify_result())):
            result = graphify_bridge.run(Path("."))
        self.assertFalse(result["used"])
        self.assertIn("threshold", result["reason"])
        self.assertIn("30", result["reason"])

    def test_at_threshold_is_accepted(self):
        """Exactly at threshold (50) should pass."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _setup_graphify_out(root)
            with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("graphify_bridge.subprocess.run",
                       side_effect=_subprocess_dispatch(
                           _ls_files_result(50), _graphify_result())):
                result = graphify_bridge.run(root)
        self.assertTrue(result["used"])

    # ------------------------------------------------------------------
    # Case 3: above threshold, graphify succeeds
    # ------------------------------------------------------------------

    def test_above_threshold_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _setup_graphify_out(root)
            with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("graphify_bridge.subprocess.run",
                       side_effect=_subprocess_dispatch(
                           _ls_files_result(55), _graphify_result())):
                result = graphify_bridge.run(root)

        self.assertTrue(result["used"])
        self.assertIn("god_nodes", result)
        self.assertIn("communities", result)
        self.assertIn("file_edges", result)
        self.assertIsInstance(result["god_nodes"], list)
        self.assertGreater(len(result["god_nodes"]), 0)

    def test_god_nodes_reflect_graph(self):
        """god_nodes should contain labels from the fixture graph."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _setup_graphify_out(root)
            with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("graphify_bridge.subprocess.run",
                       side_effect=_subprocess_dispatch(
                           _ls_files_result(55), _graphify_result())):
                result = graphify_bridge.run(root)

        labels = {"AuthService", "Router", "DatabasePool"}
        self.assertTrue(labels.intersection(set(result["god_nodes"])),
                        f"Expected some of {labels} in god_nodes, got {result['god_nodes']}")

    def test_graph_report_copied_to_raw(self):
        """GRAPH_REPORT.md must be written to context/raw/."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _setup_graphify_out(root)
            with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("graphify_bridge.subprocess.run",
                       side_effect=_subprocess_dispatch(
                           _ls_files_result(55), _graphify_result())):
                graphify_bridge.run(root)

        self.assertTrue((root / "context" / "raw" / "graphify-report.md").exists())

    def test_file_edges_use_code_relations(self):
        """file_edges should capture calls/imports edges from graph.json."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _setup_graphify_out(root)
            with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("graphify_bridge.subprocess.run",
                       side_effect=_subprocess_dispatch(
                           _ls_files_result(55), _graphify_result())):
                result = graphify_bridge.run(root)

        edges = result["file_edges"]
        self.assertIsInstance(edges, dict)
        # fixture has an edge from src/auth.py → src/routes.py
        all_sources = set(edges.keys())
        self.assertTrue(any("auth" in s for s in all_sources),
                        f"Expected auth.py as an edge source, got {all_sources}")

    # ------------------------------------------------------------------
    # Case 4: above threshold, graphify times out
    # ------------------------------------------------------------------

    def test_graphify_timeout(self):
        def _dispatch(cmd, **kwargs):
            if isinstance(cmd, list) and "ls-files" in cmd:
                return _ls_files_result(55)
            raise subprocess.TimeoutExpired(cmd, 90)

        with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
             patch("graphify_bridge.subprocess.run", side_effect=_dispatch):
            result = graphify_bridge.run(Path("."))

        self.assertFalse(result["used"])
        self.assertIn("failed", result["reason"])

    def test_graphify_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
                 patch("graphify_bridge.subprocess.run",
                       side_effect=_subprocess_dispatch(
                           _ls_files_result(55), _graphify_result(returncode=1))):
                result = graphify_bridge.run(root)

        self.assertFalse(result["used"])
        self.assertIn("failed", result["reason"])

    # ------------------------------------------------------------------
    # main() contract: always exits 0
    # ------------------------------------------------------------------

    def test_main_always_returns_zero_no_graphify(self):
        with patch("graphify_bridge.shutil.which", return_value=None):
            rc = graphify_bridge.main()
        self.assertEqual(rc, 0)

    def test_main_always_returns_zero_on_timeout(self):
        def _dispatch(cmd, **kwargs):
            if isinstance(cmd, list) and "ls-files" in cmd:
                return _ls_files_result(55)
            raise subprocess.TimeoutExpired(cmd, 90)

        with patch("graphify_bridge.shutil.which", return_value="/usr/bin/graphify"), \
             patch("graphify_bridge.subprocess.run", side_effect=_dispatch):
            rc = graphify_bridge.main()
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_GRAPH_JSON = {
    "directed": False,
    "graph": {"hyperedges": [["node-1", "node-2", "node-3"]]},
    "nodes": [
        {"id": "node-1", "label": "AuthService", "source_file": "src/auth.py"},
        {"id": "node-2", "label": "Router", "source_file": "src/routes.py"},
        {"id": "node-3", "label": "DatabasePool", "source_file": "src/db.py"},
    ],
    "links": [
        {
            "source": "node-1",
            "target": "node-2",
            "relation": "calls",
            "source_file": "src/auth.py",
        },
        {
            "source": "node-2",
            "target": "node-3",
            "relation": "imports",
            "source_file": "src/routes.py",
        },
    ],
}


def _setup_graphify_out(root: Path) -> None:
    """Pre-populate graphify-out/ and context/raw/ as graphify would."""
    out = root / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps(_GRAPH_JSON))
    (out / "GRAPH_REPORT.md").write_text("# Graphify Report\n\nGod nodes: AuthService\n")
    (root / "context" / "raw").mkdir(parents=True)


if __name__ == "__main__":
    unittest.main()
