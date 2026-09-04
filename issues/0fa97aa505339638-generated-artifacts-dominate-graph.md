# 생성 산출물이 Android 그래프의 노드 집합을 지배한다

nowinandroid_sample의 readable node 3,586개 중 3,056개(85%)가 `configuration` 종류이고, 대부분 Room이 자동 생성한 `core_database/schemas/<db>/N.json` 10개 파일에서 나온다. 같은 `fields` 키가 한 줄에서 여러 노드로 잡히기도 한다.

에이전트가 변경 대상으로 삼을 일이 없는 생성 산출물이므로, 이 상태로 M4의 PageRank·중심성·zone 집계에 들어가면 지표가 왜곡된다. `path_flags`가 이미 경로 기반 flag를 붙여 `ReadableNode.flags`에 실어 보내지만 현재 어떤 소비자도 이 값을 읽지 않는다. M4 진입 전에 flag를 집계에서 어떻게 다룰지 정해야 한다.
