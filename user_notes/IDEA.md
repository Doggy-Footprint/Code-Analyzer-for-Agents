# Ideas

## Policy-aware zone of effect

프로젝트의 문서 관리 체계와 연동하여 zone of effect의 탐색 대상을 조정한다. 문서를 참고하지 않거나 테스트를 확인하지 않는 등의 정책을 지원한다. 현재 마일스톤에는 포함하지 않는다.

## Non-trivial connections

직접 탐색 엣지는 없지만 정확 검색으로는 발견할 수 있는 연결을 별도로 식별하고 지표화한다. 예를 들면 다음과 같다.

- `search-only dependency`: 정확 검색 없이는 도달하지 못하는 연결
- `documentation-only evidence`: 관계의 근거가 문서·주석에만 존재
- `hidden coupling`: 정적 코드 관계 없이 동일 설정 키·문자열·경로로만 연결
- `candidate dilution`: 검색 결과 중 관련 target의 비율이 낮음

질문: 문서에 중요한 정보가 많다는 사실 자체를 문제로 볼 것인가, 아니면 그 정보가 코드나 구조적 관계로 대체 표현되지 않아 문서를 반드시 찾아 읽어야만 하는 경우를 문제로 볼 것인가? 후자라면 문서의 양이 아니라 유일한 근거인지가 핵심 지표가 된다.

## AI agent behavior validation

검색어 그룹을 선택하고 검색 결과 중 읽을 대상을 선택하는 탐색 모델이 실제 AI 코딩 에이전트의 행동을 충분히 근사하는지 관찰하고 검증한다. 검증 대상에는 검색 결과 전체가 노출된 뒤 남은 후보를 유지하는 방식, 새 검색과 기존 후보 사이의 선택, 검색 결과 그룹 내부의 선택 순서가 포함된다.

## Zone ranking calibration

AI 에이전트가 관련 요소를 자연스럽게 읽거나 검증하려 시도할 가능성을 나타내는 zone 가중치의 튜닝 방법과 평가 데이터셋은 추후 결정한다. 실제 에이전트 탐색 trace와 사람이 정한 검증 대상은 서로 다른 정답일 수 있으므로 구분이 필요하다. SWE-bench와 같은 기존 데이터셋이 저장소 문서를 포함해 이 목적에 충분한지도 검토한다.

## Effect importance and accessibility

target 변경의 실제 영향 중요도와 AI 에이전트가 해당 영향을 발견하고 읽을 수 있는 접근성을 별도로 계산해 비교한다. 중요하지만 접근성이 낮은 노드와 subgraph를 식별하고, 영향 관계의 강도와 검증 탐색의 용이성을 하나의 값으로 합치지 않는다. 구체적인 중요도 정의와 검증 방법은 추후 결정한다.

## Target cardinality

하나의 task에 정확히 하나의 target이 존재한다고 가정하는 것이 타당한지 재검토한다. 현재 기준선에서는 주어진 모든 target을 읽었을 때 탐색을 종료하고 대체 구현 지점은 고려하지 않는다.

## Multiple tasks per target

같은 target에 서로 다른 자연어 task를 여러 개 생성하고, task 표현에 따라 최초 검색어와 발견 비용이 어떻게 달라지는지 비교한다.

## Read behavior model

실제 AI 에이전트가 검색 결과를 확인한 뒤 파일 전체, enclosing symbol 또는 일부 line range 중 어디까지 읽는지 로그로 조사한다. 초기 readable node 경계와 이후 read 범위 확률 모델은 이 결과를 근거로 정한다.

## Occurrence representation

검색 occurrence는 독립 readable node가 아니라 query 결과의 근거로 유지하고, 도착점은 enclosing readable node로 정규화한다. 실제 agent의 line-oriented 검색·읽기를 충분히 표현하는지는 read behavior model과 함께 검증한다.

## Exploration and effect relations

target 발견에 사용하는 탐색 가능 연결과 zone of effect를 구성하는 잠재 영향 연결을 graph에서 별도 edge로 만들지, 하나의 edge 속성으로 표현할지 결정한다. 우연히 같은 문자열을 공유하는 노드는 탐색 가능하지만 서로 영향을 주지 않을 수 있다.

## Documentation effect evidence

문서나 주석의 exact mention은 탐색 연결로 만들 수 있지만, 해당 문장이 실제 주의사항·제약·영향 설명인지는 정적 일치만으로 확정하기 어렵다. 모든 mention을 낮은 confidence의 zone 후보로 둘지, sLLM 분류나 구조화된 표식을 요구할지 추후 결정한다.

## Zone cost state

zone 검증 비용을 target만 읽은 독립 상태에서 계산할지, task에서 target을 발견하며 이미 읽은 node와 실행한 query를 재사용할지 결정한다. 두 결과를 함께 제공하는 방안도 검토한다.

## Cost profile calibration

turn, search/read tool call, query output token, readable node token과 재방문을 경로 선택용 weighted cost로 합치는 임시 weight를 정한다. 원래 비용 축은 항상 별도로 보존한다. 임시 값의 교체 기준과 versioning 방법도 함께 정한다.

## Monte Carlo defaults

기대 비용 simulation의 최소 표본 수, 수렴 조건, 허용 오차와 최대 표본 수를 fixture 및 실제 저장소 결과를 근거로 정한다.

## Cost scenario ordering

세 비용이 결과 그룹 소진 규칙을 공유하고 순서 선택만 달리한다는 점은 `ROADMAP.md`에서 확정했다. 남은 질문은 재방문 확률을 0보다 크게 둘 때다. 그 경우 기대 비용이 BFS 최대 비용을 넘을 수 있으므로, 재방문을 최대 비용에도 반영할지 순서 보장을 포기할지 결정해야 한다.

## Revisit calibration

기대 비용 simulation은 node 재방문을 지원하되 초기 확률을 0으로 둔다. 사용자의 실제 AI agent 로그에서 재방문율과 조건을 추출해 이후 확률 모델을 정한다. 최소 비용과 BFS 최대 비용에는 재방문을 반영하지 않는다.

## Unreachable output

기준선은 모든 target에 도달하지 못했음을 명시하고 임의의 실패 penalty를 비용에 섞지 않는다. 실패한 query, 부분 발견 target, 조건부 비용 등의 상세 정보를 추가할지는 추후 결정한다.

## Zone cutoff interface

verification accessibility 순위에서 사용자가 확인 범위를 자르는 기본 입력을 추후 결정한다. 후보에는 node 개수, 누적 token 예산, 점수 임계값, 전체 후보 비율과 검증 강도 단계가 있다. 테스트는 입력 방식과 관계없이 기본 제외한다.

## Generated task context

task 생성 sLLM에 target 본문만 제공할지 주변 graph와 문서까지 제공할지, 생성 수와 난이도 구성을 실제 예시를 만든 뒤 결정한다. 쉬운 task에는 identifier를 허용하고 target identifier가 없는 task를 최소 하나 생성하며, 합성 여부는 metadata에 기록한다.

## Graph-wide target selection

큰 potential zone, 낮은 verification accessibility, 높은 탐색 비용, candidate dilution, bridge와 unresolved boundary 등 지표별 상위 target을 각각 선정할지 임시 weighted score로 합칠지 결정한다. 선정 이유는 어떤 방식에서도 원래 지표와 근거 경로로 보존한다.
