Golden agent-view graphs for the two bundled example repositories.

`<name>.manifest.txt` pins the scanned file list so the test does not depend on git
checkout state; `<name>.json.gz` is the gzipped `graph_to_json` output for that list.

Regenerate both after any intentional change to the agent-view output contract:

    .venv/bin/python scripts/regen_agent_view_golden.py
