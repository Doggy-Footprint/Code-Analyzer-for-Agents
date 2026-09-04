# 렌더러 표시 라벨이 단서 추출기로 유입된다

Android graph builder는 `GraphNode.label`에 이모지와 줄바꿈을 넣어 HTML 대시보드용 표시 문자열을 만든다(`"🧩 TopicScreen"`, `"⚙️ bindsUserDataRepository"`, `"📦 NewsResourceTopicCrossRef\n(2 fields)"`). `extract_clues`는 `node.label`을 identifier 단서로 사용하므로, nowinandroid_sample 기준 46개 노드가 소스에서 절대 매칭되지 않는 검색어를 만들거나 `_add`의 개행 검사에서 조용히 버려진다.

언어 그래프에 같은 심볼이 맨 이름으로도 존재해 도달성 자체는 유지되지만, 해당 framework 노드는 어떤 query의 `origin_node_ids`에도 들어가지 못한다. 표시용 라벨과 식별자를 별도 필드로 분리해야 한다.
