import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from language_analyzers.core.git_diff_core import GitDiffCore


class TestGitDiffCore(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self._git("init")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test User")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.directory,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _commit_all(self, message):
        self._git("add", ".")
        self._git("commit", "-m", message)

    def test_single_commit_reports_initial_file_as_added_with_two_added_hunk_lines(self):
        (self.directory / "initial.txt").write_text("first\nsecond\n", encoding="utf-8")
        self._commit_all("initial commit")

        info = GitDiffCore(self.directory).get_diff_info()

        self.assertTrue(info.is_git_repo)
        self.assertEqual(info.comparison_mode, "single_commit")
        self.assertFalse(info.has_uncommitted_changes)
        self.assertIsNone(info.base_commit)
        self.assertIsNotNone(info.target_commit)
        self.assertEqual((info.total_files, info.total_additions, info.total_deletions), (1, 2, 0))
        self.assertEqual(len(info.files), 1)
        file_diff = info.files[0]
        self.assertEqual((file_diff.file_path, file_diff.status), ("initial.txt", "added"))
        self.assertEqual((file_diff.additions, file_diff.deletions), (2, 0))
        self.assertEqual(len(file_diff.hunks), 1)
        hunk = file_diff.hunks[0]
        self.assertEqual((hunk.old_lines, hunk.new_lines), (0, 2))
        self.assertEqual([(line.type, line.new_lineno, line.content) for line in hunk.lines], [
            ("add", 1, "first"),
            ("add", 2, "second"),
        ])

    def test_empty_untracked_file_reports_zero_changes_and_an_empty_hunk(self):
        (self.directory / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self._commit_all("initial commit")
        (self.directory / "empty.txt").touch()

        info = GitDiffCore(self.directory).get_diff_info()

        self.assertTrue(info.is_git_repo)
        self.assertEqual(info.comparison_mode, "working_tree_vs_head")
        self.assertTrue(info.has_uncommitted_changes)
        self.assertEqual((info.total_files, info.total_additions, info.total_deletions), (1, 0, 0))
        self.assertEqual(len(info.files), 1)
        file_diff = info.files[0]
        self.assertEqual((file_diff.file_path, file_diff.status), ("empty.txt", "untracked"))
        self.assertEqual((file_diff.additions, file_diff.deletions), (0, 0))
        self.assertFalse(file_diff.is_binary)
        self.assertEqual(len(file_diff.hunks), 1)
        hunk = file_diff.hunks[0]
        self.assertEqual((hunk.old_lines, hunk.new_lines, len(hunk.lines)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
