File: 0fa97aa505339638-generated-artifacts-dominate-graph.md
Summary: Room이 생성한 schema JSON이 Android readable node의 85%를 차지해 M4 집계를 왜곡한다.
Related Files: language_analyzers/core/flags.py, agent_view/readable.py, language_analyzers/core/enrichment.py
Related Symbols: path_flags, build_readable_nodes, config_keys, ReadableNode.flags
---
File: 1d85edb512b2f937-tracked-only-file-listing.md
Summary: respect_gitignore 옵션이 실제로는 git ls-files 기반이라 추적되지 않은 새 파일을 그래프에서 누락한다.
Related Files: agent_view/scan.py, agent_view/profile.py, profiles/derived_query_rules.v1.yaml
Related Symbols: list_repository_files, _git_tracked_files, Profile.respect_gitignore
---
File: 5590523dcc4487be-display-label-leaks-into-clues.md
Summary: 이모지와 줄바꿈이 들어간 렌더러 표시 라벨을 exact query 단서 추출기가 identifier로 사용한다.
Related Files: framework_analyzers/android/graph.py, agent_view/exact_query.py
Related Symbols: extract_clues, _add, GraphNode.label, GraphNode.symbol_path
---
File: a8c91e4b7d3f5a20-kotlin-parser-cache.md
Summary: Track sharing Kotlin AST parsing between Android extraction and Kotlin graph construction as a separate performance task.
Related Files: framework_analyzers/android/analyzer.py, language_analyzers/kotlin/analyzer.py
Related Symbols: AndroidAnalyzer, KotlinAnalyzer
