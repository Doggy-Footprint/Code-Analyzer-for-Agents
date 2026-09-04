# 프레임워크 adapter의 이름 조회가 충돌한 후보를 버린다

## 현상

Android와 FastAPI graph builder는 프레임워크 컴포넌트를 이름으로 조회해 엣지를 만든다. 두 조회 모두 같은 이름이 여럿일 때 첫 항목만 남기고 나머지를 버린다.

- `framework_analyzers/android/graph.py`의 `by_name`은 `setdefault`로 첫 항목만 등록한다.
- `framework_analyzers/fastapi/graph.py`의 `_find_dep_by_name`과 `_find_schema_by_name`은 첫 매치에서 반환한다.

`GraphEdge`에는 `resolution`과 `candidates` 필드가 있으나 두 경로 모두 이를 채우지 않는다. 결과 엣지는 `resolution`이 모호하지 않다고 표시된다.

## 재현

`examples/nowinandroid_sample`의 `TopicScreen.kt`는 `TopicScreen`을 74행과 99행에 오버로드로 선언한다. `composable_by_name["TopicScreen"]`은 74행만 담는다.

- `TopicScreenPopulated`와 `TopicScreenLoading`의 `TopicScreen` 호출은 74행으로만 연결되고, 99행이 후보였다는 근거가 남지 않는다.
- 74행이 99행을 호출하는 관계는 `target.id != c.id` 조건에 걸려 자기 호출로 오인되고 엣지가 생성되지 않는다.

## 영향

M1의 framework connection specificity는 규칙의 성질이므로 이 사례에서도 `unique`가 맞다. 어긋나는 것은 엣지 인스턴스의 `resolution`이다. 도착점이 임의로 하나 선택되므로 agent-view graph는 모호성이 있는 지점을 모호하지 않은 것으로 보고하고, M4의 병목 분석은 그 지점을 후보에서 놓친다.

## 범위

`agent_view`의 계약은 바뀌지 않는다. 수정 대상은 두 graph builder의 이름 조회와, 충돌 시 `resolution`을 `AMBIGUOUS`로 두고 `candidates`를 채우는 처리다.
