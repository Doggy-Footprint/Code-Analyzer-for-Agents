#!/usr/bin/env python3
"""
Downloads a subset of android/nowinandroid (Google's official Compose + Hilt + Room +
Retrofit reference app) for testing the Android/Kotlin analyzer: a representative feature
module (Compose UI + ViewModel), the data layer (Retrofit-backed repositories), and the
database layer (Room entities/DAOs). Pulls a single tarball and extracts multiple
subpaths rather than downloading the full multi-module project.
"""

import io
import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Dict

REPO = "android/nowinandroid"
BRANCH = "main"
SUBPATHS = {
    "feature/topic": "feature_topic",
    "core/data": "core_data",
    "core/database": "core_database",
}


def download_repo_subpaths(repo: str, branch: str, subpaths: Dict[str, str], target_dir: Path) -> bool:
    url = f"https://github.com/{repo}/archive/refs/heads/{branch}.tar.gz"
    print(f"[*] Downloading {repo} ({branch}) from {url}...")

    req = urllib.request.Request(url, headers={"User-Agent": "Android-Analyzer-Downloader/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = resp.read()

        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            root_name = tar.getnames()[0].split("/")[0]

            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)

            for member in tar.getmembers():
                rel = member.name[len(root_name) + 1:]
                if not rel:
                    continue
                matched_subpath = next((sp for sp in subpaths if rel.startswith(sp + "/") or rel == sp), None)
                if matched_subpath is None:
                    continue
                local_root = subpaths[matched_subpath]
                trimmed = rel[len(matched_subpath):].lstrip("/")
                dest_file = target_dir / local_root / trimmed if trimmed else target_dir / local_root

                if member.isdir():
                    dest_file.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    f = tar.extractfile(member)
                    if f:
                        with open(dest_file, "wb") as out:
                            out.write(f.read())
        print(f"[✓] Extracted {', '.join(subpaths)} to {target_dir}")
        return True
    except Exception as e:
        print(f"[!] Error downloading {repo}: {e}")
        return False


def main():
    base_dir = Path(__file__).parent.resolve()
    target_dir = base_dir / "nowinandroid_sample"
    download_repo_subpaths(REPO, BRANCH, SUBPATHS, target_dir)
    print("\nDownload process completed.")


if __name__ == "__main__":
    main()
