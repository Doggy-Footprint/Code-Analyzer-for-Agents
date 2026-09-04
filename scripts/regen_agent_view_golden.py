"""Regenerate the agent-view golden fixtures. See tests/fixtures/agent_view/README.md."""

import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.agent_view_golden_cases import GOLDEN_CASES, build_json, scan_manifest  # noqa: E402


def main() -> None:
    for case in GOLDEN_CASES:
        paths = scan_manifest(case)
        payload = build_json(case, paths)
        case.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        case.manifest_path.write_text("\n".join(paths) + "\n", encoding="utf-8")
        with gzip.GzipFile(case.golden_path, "wb", mtime=0) as handle:
            handle.write(payload.encode("utf-8"))
        print(f"[+] {case.name}: {len(paths)} files, {len(payload)} bytes")


if __name__ == "__main__":
    main()
