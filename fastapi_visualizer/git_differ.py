"""
Git Differ Engine for FastAPI Codebases.
Extracts differences after the latest git commit (including untracked files),
or compares the last two git commits if the working directory is clean.
Correlates git changes with FastAPI architecture components.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import (
    GitCommitInfo,
    GitDiffHunk,
    GitDiffInfo,
    GitDiffLine,
    GitFileDiff,
    ProjectArchitecture,
)


class GitDiffer:
    def __init__(self, project_path: Union[str, Path]):
        self.project_path = Path(project_path).resolve()
        self.repo_root: Optional[Path] = None
        self.rel_prefix: str = ""

    def get_diff_info(self, arch: Optional[ProjectArchitecture] = None) -> GitDiffInfo:
        if not self._init_git_repo():
            return GitDiffInfo(
                is_git_repo=False,
                comparison_mode="none",
                mode_description="Not a Git repository",
                error_message="Project directory is not part of a Git repository.",
            )

        try:
            has_changes, status_lines = self._check_uncommitted_changes()
            if has_changes:
                diff_info = self._extract_working_tree_diff(status_lines)
            else:
                commit_count = self._get_commit_count()
                if commit_count >= 2:
                    diff_info = self._extract_last_two_commits_diff()
                elif commit_count == 1:
                    diff_info = self._extract_single_commit_diff()
                else:
                    diff_info = GitDiffInfo(
                        is_git_repo=True,
                        comparison_mode="none",
                        mode_description="Repository has no commits",
                        error_message="Git repository has no commits.",
                    )

            if arch:
                self._correlate_with_architecture(diff_info, arch)

            return diff_info
        except Exception as e:
            return GitDiffInfo(
                is_git_repo=True,
                comparison_mode="none",
                mode_description="Error extracting Git diff",
                error_message=str(e),
            )

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.project_path)] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except Exception as e:
            return -1, "", str(e)

    def _init_git_repo(self) -> bool:
        code, out, _ = self._run_git(["rev-parse", "--is-inside-work-tree"])
        if code != 0 or out.strip() != "true":
            return False

        code, root_out, _ = self._run_git(["rev-parse", "--show-toplevel"])
        if code != 0 or not root_out.strip():
            return False

        self.repo_root = Path(root_out.strip()).resolve()
        try:
            rel = self.project_path.relative_to(self.repo_root)
            self.rel_prefix = "" if str(rel) == "." else str(rel)
        except ValueError:
            self.rel_prefix = ""

        return True

    def _get_commit_info(self, ref: str) -> Optional[GitCommitInfo]:
        code, out, _ = self._run_git([
            "log", "-1", "--format=%H%x00%h%x00%an%x00%ae%x00%ad%x00%s",
            "--date=iso", ref
        ])
        if code != 0 or not out.strip():
            return None

        parts = out.strip().split("\x00")
        if len(parts) >= 6:
            return GitCommitInfo(
                hash=parts[0],
                short_hash=parts[1],
                author=parts[2],
                email=parts[3],
                date=parts[4],
                message=parts[5],
            )
        return None

    def _get_commit_count(self) -> int:
        code, out, _ = self._run_git(["rev-list", "--count", "HEAD"])
        if code == 0 and out.strip().isdigit():
            return int(out.strip())
        return 0

    def _check_uncommitted_changes(self) -> Tuple[bool, List[str]]:
        code, out, _ = self._run_git(["status", "--porcelain=v1", "-uall", "."])
        if code != 0:
            return False, []
        lines = [line for line in out.splitlines() if line.strip()]
        return len(lines) > 0, lines

    def _normalize_path(self, raw_path: str) -> str:
        # git paths are repo-root-relative, but callers want them relative to
        # project_path (which may be a subdirectory of the repo).
        p = raw_path.strip()
        if p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        if self.rel_prefix and (p == self.rel_prefix or p.startswith(self.rel_prefix + "/")):
            return p[len(self.rel_prefix) + 1:] if p.startswith(self.rel_prefix + "/") else "."
        return p

    def _extract_working_tree_diff(self, status_lines: List[str]) -> GitDiffInfo:
        base_commit = self._get_commit_info("HEAD")

        _, tracked_diff_out, _ = self._run_git(["diff", "-M", "HEAD", "--", "."])
        file_diffs = self._parse_unified_diff(tracked_diff_out)
        existing_paths = {f.file_path for f in file_diffs}

        _, untracked_out, _ = self._run_git(["ls-files", "--others", "--exclude-standard", "."])
        untracked_files = [line.strip() for line in untracked_out.splitlines() if line.strip()]

        for untracked_rel_path in untracked_files:
            norm_path = self._normalize_path(untracked_rel_path)
            if norm_path in existing_paths:
                continue

            full_file_path = self.project_path / norm_path
            if not full_file_path.is_file() and self.repo_root:
                full_file_path = self.repo_root / untracked_rel_path

            if not full_file_path.is_file():
                continue

            untracked_diff = self._create_untracked_file_diff(norm_path, full_file_path)
            file_diffs.append(untracked_diff)
            existing_paths.add(norm_path)

        total_add = sum(f.additions for f in file_diffs)
        total_del = sum(f.deletions for f in file_diffs)

        return GitDiffInfo(
            is_git_repo=True,
            comparison_mode="working_tree_vs_head",
            mode_description="Uncommitted changes after latest commit (Working Tree ↔ HEAD)",
            base_commit=base_commit,
            target_commit=None,
            target_name="Working Tree (Uncommitted Changes)",
            has_uncommitted_changes=True,
            total_files=len(file_diffs),
            total_additions=total_add,
            total_deletions=total_del,
            files=file_diffs,
        )

    def _extract_last_two_commits_diff(self) -> GitDiffInfo:
        target_commit = self._get_commit_info("HEAD")
        base_commit = self._get_commit_info("HEAD~1")

        _, diff_out, _ = self._run_git(["diff", "-M", "HEAD~1", "HEAD", "--", "."])
        file_diffs = self._parse_unified_diff(diff_out)

        total_add = sum(f.additions for f in file_diffs)
        total_del = sum(f.deletions for f in file_diffs)

        return GitDiffInfo(
            is_git_repo=True,
            comparison_mode="last_two_commits",
            mode_description="Clean working tree — Comparing last 2 git commits (HEAD ↔ HEAD~1)",
            base_commit=base_commit,
            target_commit=target_commit,
            target_name=f"HEAD ({target_commit.short_hash if target_commit else 'Latest'})",
            has_uncommitted_changes=False,
            total_files=len(file_diffs),
            total_additions=total_add,
            total_deletions=total_del,
            files=file_diffs,
        )

    def _extract_single_commit_diff(self) -> GitDiffInfo:
        target_commit = self._get_commit_info("HEAD")
        # git's fixed hash for the empty tree object, used to diff a single commit as if it were a full add.
        empty_tree_sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

        _, diff_out, _ = self._run_git(["diff", "-M", empty_tree_sha, "HEAD", "--", "."])
        file_diffs = self._parse_unified_diff(diff_out)

        total_add = sum(f.additions for f in file_diffs)
        total_del = sum(f.deletions for f in file_diffs)

        return GitDiffInfo(
            is_git_repo=True,
            comparison_mode="single_commit",
            mode_description="Clean working tree — Showing initial commit (HEAD)",
            base_commit=None,
            target_commit=target_commit,
            target_name=f"HEAD ({target_commit.short_hash if target_commit else 'Initial'})",
            has_uncommitted_changes=False,
            total_files=len(file_diffs),
            total_additions=total_add,
            total_deletions=total_del,
            files=file_diffs,
        )

    def _create_untracked_file_diff(self, norm_path: str, full_path: Path) -> GitFileDiff:
        is_binary = False
        content_lines: List[str] = []
        try:
            with open(full_path, "rb") as bf:
                chunk = bf.read(8000)
                if b"\x00" in chunk:
                    is_binary = True
            
            if not is_binary:
                with open(full_path, "r", encoding="utf-8", errors="replace") as tf:
                    content_lines = tf.read().splitlines()
        except Exception:
            is_binary = True

        if is_binary:
            return GitFileDiff(
                file_path=norm_path,
                status="untracked",
                additions=0,
                deletions=0,
                is_binary=True,
                raw_diff=f"Untracked binary file: {norm_path}",
                hunks=[],
            )

        num_lines = len(content_lines)
        diff_lines = [
            GitDiffLine(type="add", old_lineno=None, new_lineno=i + 1, content=line)
            for i, line in enumerate(content_lines)
        ]
        hunk = GitDiffHunk(
            header=f"@@ -0,0 +1,{max(1, num_lines)} @@",
            old_start=0,
            old_lines=0,
            new_start=1,
            new_lines=num_lines,
            lines=diff_lines,
        )

        synthetic_diff = (
            f"diff --git a/{norm_path} b/{norm_path}\n"
            f"new file mode 100644\n"
            f"--- /dev/null\n"
            f"+++ b/{norm_path}\n"
            f"@@ -0,0 +1,{max(1, num_lines)} @@\n"
            + "\n".join("+" + line for line in content_lines)
        )

        return GitFileDiff(
            file_path=norm_path,
            status="untracked",
            additions=num_lines,
            deletions=0,
            is_binary=False,
            raw_diff=synthetic_diff,
            hunks=[hunk],
        )

    def _parse_unified_diff(self, diff_text: str) -> List[GitFileDiff]:
        if not diff_text.strip():
            return []

        file_diffs: List[GitFileDiff] = []
        raw_sections = re.split(r"(?m)^diff --git ", diff_text)

        for raw_sec in raw_sections:
            if not raw_sec.strip():
                continue
            raw_sec = "diff --git " + raw_sec
            lines = raw_sec.splitlines()

            first_line = lines[0]
            m = re.match(r"^diff --git a/(.*?) b/(.*?)$", first_line)
            old_raw_path = m.group(1) if m else ""
            new_raw_path = m.group(2) if m else ""

            status = "modified"
            is_binary = False
            rename_from = None

            hunk_start_idx = -1
            for idx, line in enumerate(lines[1:], start=1):
                if line.startswith("new file mode"):
                    status = "added"
                elif line.startswith("deleted file mode"):
                    status = "deleted"
                elif line.startswith("rename from"):
                    status = "renamed"
                    rename_from = line.replace("rename from", "").strip()
                elif line.startswith("rename to"):
                    new_raw_path = line.replace("rename to", "").strip()
                elif "Binary files" in line or "GIT binary patch" in line:
                    is_binary = True
                elif line.startswith("@@"):
                    hunk_start_idx = idx
                    break

            display_path = self._normalize_path(new_raw_path if status != "deleted" else old_raw_path)
            display_old_path = self._normalize_path(rename_from or old_raw_path) if status == "renamed" else None

            hunks: List[GitDiffHunk] = []
            additions = 0
            deletions = 0

            if not is_binary and hunk_start_idx != -1:
                current_hunk: Optional[GitDiffHunk] = None
                curr_old_line = 0
                curr_new_line = 0

                for line in lines[hunk_start_idx:]:
                    if line.startswith("@@"):
                        hm = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$", line)
                        if hm:
                            old_start = int(hm.group(1))
                            old_lines = int(hm.group(2)) if hm.group(2) is not None else 1
                            new_start = int(hm.group(3))
                            new_lines = int(hm.group(4)) if hm.group(4) is not None else 1
                            curr_old_line = old_start
                            curr_new_line = new_start
                            current_hunk = GitDiffHunk(
                                header=line,
                                old_start=old_start,
                                old_lines=old_lines,
                                new_start=new_start,
                                new_lines=new_lines,
                                lines=[],
                            )
                            hunks.append(current_hunk)
                        continue

                    if current_hunk is None:
                        continue

                    if line.startswith("+") and not line.startswith("+++"):
                        additions += 1
                        current_hunk.lines.append(
                            GitDiffLine(
                                type="add",
                                old_lineno=None,
                                new_lineno=curr_new_line,
                                content=line[1:],
                            )
                        )
                        curr_new_line += 1
                    elif line.startswith("-") and not line.startswith("---"):
                        deletions += 1
                        current_hunk.lines.append(
                            GitDiffLine(
                                type="del",
                                old_lineno=curr_old_line,
                                new_lineno=None,
                                content=line[1:],
                            )
                        )
                        curr_old_line += 1
                    elif line.startswith(" "):
                        current_hunk.lines.append(
                            GitDiffLine(
                                type="context",
                                old_lineno=curr_old_line,
                                new_lineno=curr_new_line,
                                content=line[1:],
                            )
                        )
                        curr_old_line += 1
                        curr_new_line += 1

            file_diffs.append(
                GitFileDiff(
                    file_path=display_path,
                    status=status,
                    additions=additions,
                    deletions=deletions,
                    old_path=display_old_path,
                    raw_diff=raw_sec,
                    is_binary=is_binary,
                    hunks=hunks,
                )
            )

        return file_diffs

    def _correlate_with_architecture(self, diff_info: GitDiffInfo, arch: ProjectArchitecture):
        def matches_file(element_file_path: str, diff_file_path: str) -> bool:
            if not element_file_path or not diff_file_path:
                return False
            norm_elem = element_file_path.replace("\\", "/").lstrip("./")
            norm_diff = diff_file_path.replace("\\", "/").lstrip("./")
            return norm_elem == norm_diff or norm_elem.endswith("/" + norm_diff) or norm_diff.endswith("/" + norm_elem)

        impacted_endpoints = []
        for ep in arch.endpoints:
            for f in diff_info.files:
                if matches_file(ep.file_path, f.file_path):
                    ep_meta = {
                        "id": ep.id,
                        "method": ep.http_method,
                        "path": ep.full_path or ep.path,
                        "func": ep.function_name,
                        "file": ep.file_path,
                        "line": ep.line_number,
                    }
                    impacted_endpoints.append(ep_meta)
                    f.impacted_components.append({
                        "type": "endpoint",
                        "label": f"{ep.http_method} {ep.full_path or ep.path}",
                        "id": ep.id,
                    })

        impacted_routers = []
        for r in arch.routers:
            for f in diff_info.files:
                if matches_file(r.file_path, f.file_path):
                    r_meta = {
                        "id": r.id,
                        "var_name": r.var_name,
                        "prefix": r.prefix,
                        "file": r.file_path,
                        "line": r.line_number,
                    }
                    impacted_routers.append(r_meta)
                    f.impacted_components.append({
                        "type": "router",
                        "label": f"Router: {r.var_name}",
                        "id": r.id,
                    })

        impacted_dependencies = []
        for d in arch.dependencies:
            for f in diff_info.files:
                if matches_file(d.file_path, f.file_path):
                    d_meta = {
                        "id": d.id,
                        "name": d.name,
                        "kind": d.kind,
                        "file": d.file_path,
                        "line": d.line_number,
                    }
                    impacted_dependencies.append(d_meta)
                    f.impacted_components.append({
                        "type": "dependency",
                        "label": f"Dep: {d.name}",
                        "id": d.id,
                    })

        impacted_schemas = []
        for s in arch.schemas:
            for f in diff_info.files:
                if matches_file(s.file_path, f.file_path):
                    s_meta = {
                        "id": s.id,
                        "name": s.name,
                        "file": s.file_path,
                        "line": s.line_number,
                    }
                    impacted_schemas.append(s_meta)
                    f.impacted_components.append({
                        "type": "schema",
                        "label": f"Model: {s.name}",
                        "id": s.id,
                    })

        diff_info.impacted_endpoints = list({e["id"]: e for e in impacted_endpoints}.values())
        diff_info.impacted_routers = list({r["id"]: r for r in impacted_routers}.values())
        diff_info.impacted_dependencies = list({d["id"]: d for d in impacted_dependencies}.values())
        diff_info.impacted_schemas = list({s["id"]: s for s in impacted_schemas}.values())
