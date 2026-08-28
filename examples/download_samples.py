#!/usr/bin/env python3
"""
Downloads moderate-sized open-source FastAPI sample projects for testing the visualizer:
1. nsidnev/fastapi-realworld-example-app (Conduit blogging backend with nested routers, dependencies, schemas)
2. fastapi/full-stack-fastapi-template (Official template backend by FastAPI author)
"""

import io
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


def download_github_repo_tar(repo: str, branch: str, target_dir: Path, subpath: str = None):
    url = f"https://github.com/{repo}/archive/refs/heads/{branch}.tar.gz"
    print(f"[*] Downloading {repo} ({branch}) from {url}...")
    
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "FastAPI-Visualizer-Downloader/1.0"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
            
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
            # Find the root folder name inside archive (e.g. fastapi-realworld-example-app-master)
            root_name = tar.getnames()[0].split("/")[0]
            
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            
            for member in tar.getmembers():
                rel = member.name[len(root_name) + 1:]
                if not rel:
                    continue
                if subpath:
                    if not rel.startswith(subpath):
                        continue
                    rel = rel[len(subpath):].lstrip("/")
                    if not rel:
                        continue
                
                dest_file = target_dir / rel
                if member.isdir():
                    dest_file.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    f = tar.extractfile(member)
                    if f:
                        with open(dest_file, "wb") as out:
                            out.write(f.read())
        print(f"[✓] Extracted to {target_dir}")
        return True
    except Exception as e:
        print(f"[!] Error downloading {repo}: {e}")
        return False


def main():
    base_dir = Path(__file__).parent.resolve()
    
    # 1. RealWorld FastAPI App
    realworld_dir = base_dir / "realworld_app"
    download_github_repo_tar(
        repo="nsidnev/fastapi-realworld-example-app",
        branch="master",
        target_dir=realworld_dir
    )
    
    # 2. Official Full-Stack FastAPI Template (Backend only)
    template_dir = base_dir / "official_template"
    download_github_repo_tar(
        repo="fastapi/full-stack-fastapi-template",
        branch="master",
        target_dir=template_dir,
        subpath="backend"
    )

    print("\nDownload process completed.")


if __name__ == "__main__":
    main()
