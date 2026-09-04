# Goal: AI Agent Repository Exploration Analyzer

## 목적

이 프로젝트는 AI 코딩 에이전트가 저장소에서 변경 대상을 찾고, 그 변경이 영향을 줄 수 있는 범위를 확인하는 과정을 정적 그래프로 근사한다. 분석기는 다음 질문에 답한다.

- 에이전트가 task를 받고 target을 발견하려면 무엇을 검색하고 얼마나 읽어야 하는가?
- target을 수정하기 전에 어디까지 읽고 검증해야 하는가?
- 필요한 대상이 존재하지만 검색 후보에 묻히거나 연결이 약해 놓치기 쉬운 지점은 어디인가?
- 어떤 노드·엣지·subgraph가 탐색 turn, tool call, token 소비를 증가시키는가?
- 저장소 구조를 어떻게 바꾸면 이 비용과 누락 위험을 줄일 수 있는가?

그래프는 저장소의 의미를 완전히 복원하지 않는다. 에이전트가 코드·문서·주석에서 얻을 수 있는 명시적 단서, 정확 검색, 읽은 identifier를 고정된 규칙표로 변형한 검색, 정적 관계, 프레임워크 규칙을 모델링한다. 규칙표 밖의 표현을 외부 지식이나 의미적 유사성으로 떠올리는 추론은 분석 범위에서 제외한다. 따라서 결과는 AI 에이전트 관점에서 본 저장소의 결정적 근사다.

## 핵심 개념

- `task`: AI 에이전트에게 주어진 자연어 요청이다.
- `query`: 에이전트가 저장소에서 다음 후보를 노출하기 위해 실행하는 검색 행동이다.
- `seed query`: task를 받은 에이전트가 처음 실행할 검색어다.
- `target`: task를 완료하기 위해 발견하고 읽어야 하는 하나 이상의 노드다.
- `readable node`: 에이전트가 독립적으로 읽을 수 있는 파일, 코드 단위, 설정, 테스트, 문서 등의 저장소 엔티티다.
- `exploration connection`: 현재까지 읽은 정보에서 query를 만들고 다음 readable node를 발견할 수 있는 연결이다.
- `potential zone of effect`: target 변경의 영향을 받을 수 있으므로 수정 전 읽고 검증해야 하는 전체 후보 범위다.
- `verification accessibility`: zone의 각 대상까지 에이전트가 자연스럽게 탐색하고 검증을 시도할 가능성을 나타내는 별도 순위다. 영향의 중요도를 뜻하지 않는다.
- `structural bottleneck`: target 발견 또는 zone 검증 비용을 반복적으로 증가시키는 노드, query, edge 또는 subgraph다.
- `list query`: 파일 내용이 아니라 경로 이름공간을 대상으로 결과를 노출하는 검색 행동이다.
- `refinement query`: 이미 노출된 결과 집합에서 결정적으로 생성해 그 부분집합을 노출하는 query다.
- `hint`: query 결과가 도착 노드를 읽기 전에 노출하는 결정적 정보다. query node와 readable node를 잇는 엣지의 속성이며 독립 노드가 아니다.
- `entry document`: 에이전트가 검색 이전에 읽는 저장소 진입 문서다.
- `exploration policy`: 대기 query와 결과 노드의 선택 순서를 지배하는 규칙이다.

## 그래프 모델

그래프는 저장소 엔티티뿐 아니라 탐색 행동을 표현한다.

### Readable nodes

파일, 모듈, 클래스, 함수, 메서드, 타입, 설정, 테스트, 문서, API endpoint 등 에이전트가 읽을 수 있는 대상을 표현한다. query 결과의 도착점은 occurrence를 감싸는 symbol 노드다.

read 비용은 symbol 범위가 아니라 그 symbol이 속한 read 단위 전체의 token으로 계산한다. 에이전트는 symbol만 잘라 읽기보다 파일을 열어 읽기 때문이다.

read 단위는 파일이되, 파일 token이 임계 N을 넘으면 청크다. N 이하 파일은 파일 전체가 하나의 read 단위이고, 초과 파일은 symbol 경계에 정렬된 N token 이하의 최대 구간들로 분할한다. 라인 윈도우로 자르면 청크 집합이 파서 상태에 따라 흔들려 결정적 serialization이 깨지므로 경계는 symbol에 정렬한다. N은 profile 파일에 두고 실제 read 도구의 기본 limit에서 유도한 값과 그 근거를 함께 기록한다.

- 같은 read 단위의 다른 symbol에 도달하는 read는 tool call과 token 비용이 0이다.
- 그 read 단위에 있는 target은 읽은 시점에 모두 발견한 것으로 본다.
- 그 read 단위의 모든 symbol에서 생성되는 query는 읽은 시점에 후보가 된다.
- 같은 파일의 다른 청크는 읽지 않은 상태로 남는다. 그 청크로 이동하려면 read tool call을 다시 쓰거나 scope를 그 파일로 한정한 refinement query를 쓴다.

파일 전체를 언제나 하나의 read 단위로 두면 거대 단일 파일이 가장 저렴한 구조로 평가되어, 병목을 드러낸다는 목적과 반대 방향의 편향이 생긴다. 임계 N은 그 편향을 제거하기 위한 것이다.

read 단위는 노드 경계가 아니라 비용 모델의 결정이므로, symbol 수준의 관계 방향과 zone 전파는 그대로 유지한다.

### 기본 제외 대상

에이전트가 목적을 갖고 검색·판독하지 않는 파일은 readable node로 만들지 않는다. lockfile, 바이너리, build 산출물, generated 코드는 기본적으로 제외하며, 제외 규칙은 버전 관리되는 설정 파일에 두고 저장소별로 재정의할 수 있다. 제외된 파일은 target이나 zone 의 대상이 되지 않는다.

### Query nodes and result groups

query node는 동일한 탐색 행동으로 한 번에 노출되는 결과 그룹을 표현한다. query 후보는 exact query와 derived query 두 종류이며, 둘 다 이미 읽은 저장소 내용에서 결정적으로 생성한다.

exact query는 다음 명시적 단서를 그대로 검색한다.

- identifier와 qualified name
- 문자열 리터럴
- 파일·모듈 경로
- 설정 키
- URL과 route
- 오류 메시지
- 문서 및 주석에 코드 형태로 적힌 표현

derived query는 이미 읽은 identifier를 고정된 규칙표로 변형해 생성한다. 에이전트가 완전 일치 검색과 함께 수행하는 부분 일치 검색을 모방하기 위한 것이며, exact 결과가 없을 때만 쓰는 fallback이 아니라 정식 query 종류다. 허용 변형은 다음으로 한정한다.

- camelCase, PascalCase, snake_case, kebab-case와 숫자 경계의 토큰 분해
- 분해된 토큰과 인접 토큰의 조합
- 대소문자 정규화, 단복수 변형, 규칙표에 등록된 접두사·접미사 제거

규칙표 밖의 변형과 외부 동의어 사전은 사용하지 않는다. 규칙표는 버전 관리하고 결과에 사용한 버전을 기록한다.

#### 검색 surface

검색 대상은 파일 내용과 경로 이름공간 둘 다이다. 정확 검색은 코드·문서·주석 전체를 대상으로 하며, exact query와 derived query는 파일 내용과 정규화된 저장소 상대 경로 양쪽에 매칭한다. 경로·파일명 자체가 검색 가능한 이름공간이므로 derived 규칙표는 경로 토큰에 그대로 재사용한다. 경로를 파일 내용에 적힌 문자열로만 다루면, 파일명으로 한 번에 잡히는 target의 발견 비용이 구조적으로 과대평가된다.

경로 이름공간만을 대상으로 하는 검색 행동은 list query로 표현한다. 결과 그룹은 일치한 경로 집합, 도착 노드는 해당 파일이며, 결과 token은 노출된 경로 문자열로 계산한다. 디렉터리 열람도 list query이며 비용이 0인 노드가 아니다. 엔트리가 많은 디렉터리는 실제로 비싸고, 이를 공짜로 두면 거대 파일을 공짜로 두는 것과 같은 종류의 왜곡이 다른 축에서 재발한다. seed 단계의 루트 트리 열람은 기본 허용하되 깊이와 엔트리 상한을 profile에 두고 출력 token은 정상 과금한다.

#### Occurrence와 hint

검색 occurrence는 독립 readable node로 만들지 않는다. occurrence는 query 결과의 근거이며 실제 도착점은 enclosing readable node다. query 출력 비용은 실제 검색 결과의 모든 occurrence를 기준으로 계산한다.

occurrence가 도착 노드를 읽기 전에 노출하는 정보는 버리지 않고 query node → readable node 엣지의 hint 속성으로 싣는다. hint는 occurrence와 검색 도구 출력 형식의 결정적 투영이며, 출력 형식은 계약에서 고정하는 파라미터다. 엣지에 싣는 값은 다음으로 한정한다.

- 도착 노드의 경로·파일명·symbol 이름
- occurrence의 구문 역할: 선언, import, 호출, 문자열 리터럴, 주석, 문서 mention, 테스트
- 노출된 줄 window 안의 identifier 집합

hint로 쓸 수 있는 정보는 `query 결과 token` 축에서 이미 비용을 지불한 텍스트로 한정한다. 따라서 기본 출력 형식은 context 0줄의 매치 줄만이며, window를 넓히면 hint 표면과 결과 token 비용이 함께 커진다. 이 불변식 때문에 hint는 새 비용 축을 만들지 않는다.

#### Read 없는 query 생성

hint만 보고 다음 query를 만드는 경로를 인정한다. 즉 read를 거치지 않고 query node에서 다른 query node로 가는 엣지가 존재한다. 실제 에이전트는 검색 결과 줄에 보이는 identifier를 파일을 열지 않고 곧바로 다시 검색한다.

모든 query가 read에서만 생성된다는 대안을 채택하지 않는 이유는, 그 제약이 결과 줄에서 이미 비용을 지불해 노출된 단서를 그래프에서 표현 불가능하게 만들기 때문이다. 대신 이 엣지는 query 그래프의 분기 계수를 크게 올리므로 다음 상한을 함께 둔다.

- 생성 후보 identifier는 노출된 줄 window 안의 것으로만 한정한다.
- 결과 그룹당 생성 query 수 상한을 profile에 둔다.
- 중복은 query 동등성 규칙으로 제거한다.

#### Refinement query

결과 그룹 크기가 임계 K를 넘으면 query를 버리는 대신 좁히는 refinement query를 만든다. 후보는 이미 노출된 결과 집합에서만 결정적으로 생성하며 저장소 전역 지식은 쓰지 않는다.

- 결과에 등장한 디렉터리 경계의 경로 prefix
- 결과에 등장한 확장자
- 규칙표에 등록된 토큰 결합

refinement는 query → query 엣지이고 search tool call을 한 번 쓰며, 결과 그룹은 부모 그룹의 부분집합이다. refinement 깊이와 query당 후보 수에 상한을 두지 않으면 BFS 최대 비용이 병적인 refinement 연쇄에 지배되어, 저장소가 아니라 상한의 부재를 측정하게 된다. 두 상한은 profile의 필수 값이며 K와 함께 결과에 기록한다.

#### query 동등성과 중복 실행

query node의 identity는 query 종류, 정규화된 query 문자열, 검색 surface와 scope, 규칙표 버전의 조합이다.

- 서로 다른 노드가 같은 문자열을 만들면 같은 query node이며, 발견 출처는 여러 in-edge로 표현한다. 여러 target에서 반복되는 공통 병목은 이 형태로 드러난다.
- scope가 다르면 다른 query node다. 파일로 scope를 한정한 refinement는 전역 query와 구분된다.
- 이미 실행한 query가 대기열에 다시 들어오면 비용 없이 폐기하고 중복 억제 횟수를 기록한다.

이 규칙이 없으면 같은 저장소와 설정에서도 실행마다 비용이 달라져 M1의 재현성 완료 조건을 정의할 수 없다.

### 연결의 특정력과 framework connection

연결은 도착 노드를 얼마나 좁히는지에 따라 두 종류로 나뉜다. 이 구분은 framework 고유의 성질이 아니라 모든 exploration connection의 일반 속성이다.

- 도착 노드를 유일하게 특정하면 query node 없이 read 한 번으로 이동한다.
- 후보 집합만 좁히면 좁혀진 집합을 결과 그룹으로 갖는 query node를 만든다.

언어의 import와 qualified name 해석이 첫 번째에 해당한다. `import a.b.Foo`를 읽은 에이전트는 검색하지 않고 해당 파일을 연다. 이를 일반 검색과 같은 비용으로 두면 언어가 제공하는 해석 가능성의 이점이 모델에서 사라진다. 다만 유일 특정은 resolver가 실제로 성공했을 때만 성립한다. wildcard import, re-export, 동적 import, 다중 후보 모듈은 후보 축소로 처리하고 M4의 unresolved boundary 진단으로 보고한다.

프레임워크 규칙으로 성립하는 연결은 exact 문자열 일치 근거가 없어도 그래프에 포함한다. 기준은 근거의 형태가 아니라 에이전트가 그 규칙만으로 이동할 수 있는지다. 각 프레임워크 규칙이 유일 특정인지 후보 축소인지 adapter에 명시하고, 결과에서 근거 규칙과 함께 보고한다.

### 진입 문서

에이전트는 검색 이전에 루트 README, AGENTS.md, CLAUDE.md 같은 진입 문서를 읽는다. 진입 문서 목록은 버전 관리되는 설정에 두고 저장소별로 재정의한다.

진입 문서는 탐색 시작 시점에 읽은 것으로 처리하고, 거기서 생성되는 query는 최초 대기 query 집합에 들어간다. harness가 자동 주입하는 문서는 read tool call 비용이 0이고 token 비용은 정상 과금한다. 자동 주입 여부는 설정에 표시한다.

진입 문서가 언급하는 문서와 코드는 일괄로 읽은 것으로 처리하지 않는다. 언급 대상은 일반 exploration connection으로 두며, 경로나 identifier가 resolve되면 유일 특정 규칙에 따라 read 한 번으로 도달한다. 언급된 대상을 발견 처리하면 진입 문서가 실제로 발견 비용을 낮추는지가 정의상 측정 불가능해지고, 문서에 파일 목록을 나열한 저장소가 자동으로 유리해진다. 진입 문서의 효과는 가정이 아니라 비용 차이로 관측한다.

### 탐색 범위의 한계

분석기는 다음 행동을 일반 탐색 연결로 만들지 않는다.

- 현재까지 읽은 내용에 없는 표현을 의미적으로 연상하는 행동
- 저장소 외부 지식만으로 만들어진 비결정적 검색어
- 실제 에이전트가 사용할 수 없는 analyzer 내부 정보로 target을 직접 선택하는 행동

derived query, 경로 검색과 list query, hint 기반 query 생성, refinement query, 프레임워크 연결은 여기에 해당하지 않는다. 모두 이미 읽었거나 이미 노출되어 비용을 지불한 내용, 또는 고정된 규칙에서 같은 결과로 재생성되므로 의미적 연상과 구분한다.

분석 가능한 직접 연결이 없고 특정 exact query를 실행해야만 발견되는 관계는 별도 진단 후보다.

## Target 발견 모델

### 최초 query 생성

명시적 seed query가 없으면 Qwen3.5-4B를 탐색 모방용 sLLM으로 사용한다. sLLM은 task만 입력받고 최초 검색어 집합을 생성한다. 저장소 파일 목록, graph 또는 정답 target은 제공하지 않는다. 생성된 검색어는 하나의 최초 미실행 query 집합으로 사용하며, 검색어별 독립 시나리오로 분리하지 않는다.

모델 revision, prompt, decoding 설정과 생성 결과를 기록한다. 생성 query는 target 예측이 아니라 에이전트의 첫 검색 행동을 재현하기 위한 입력이다.

### 탐색 정책과 turn

대기 query와 결과 노드의 선택 순서는 exploration policy가 지배한다. 정책은 파라미터이며 기본값은 `bfs-exhaust`다.

`bfs-exhaust`의 한 turn은 다음과 같다.

1. 아직 실행하지 않은 query 중 하나를 선택한다.
2. query 결과 전체를 노출하고 모든 raw occurrence의 출력 token 비용을 기록한다.
3. hint를 근거로 고유 도착 노드의 순서를 정한다.
4. 결과 노드를 하나씩 읽는다.
5. 읽은 노드와 hint에서 생성된 새 query는 현재 결과 그룹을 모두 확인할 때까지 대기시킨다.
6. 현재 그룹을 소진하면 대기 중인 query에서 다음 query를 선택한다.

결과 그룹 소진 규칙을 기본값으로 두는 이유는, 이것이 노출된 결과와 read 비용을 빠짐없이 계상하는 보수적 기준선이기 때문이다. 실제 에이전트는 강한 단서를 얻으면 현재 그룹을 버리고 pivot하므로 이 기본값은 비용을 과대평가하는 쪽으로 치우친다. 대안인 best-first pivot 정책은 hint를 우선순위로 삼아 그룹 소진 전에 새 query로 이동하며, 같은 그래프 위에서 정책만 바꿔 실행한다. 이 선택은 최소·기대·최대 비용의 값을 모두 지배하므로 정책은 코드 상수가 아니라 profile 파일의 값으로 두고, 모든 결과에 사용한 정책을 기록한다.

세 비용은 고정된 하나의 정책 안에서만 정의된다. 정책이 다른 결과끼리는 비교 대상이 아니며, 특히 `최대 비용 = BFS 최대`라는 정의는 `bfs-exhaust` 정책에 종속된다.

`query → result 선택 → read`를 graph depth 1의 탐색 turn으로 본다. query와 read의 tool call 및 token 비용은 별도 축으로 기록한다.

탐색 turn은 직렬 등가 turn이다. 실제 에이전트는 한 turn에 여러 검색을 병렬로 던지므로 이 축은 실제 agent 로그의 turn 수와 직접 비교하는 대상이 아니다. 병렬 배치는 보정되지 않은 행동 파라미터이므로 모델에 넣지 않는다.

검색 결과에 target이 나타난 것만으로는 발견한 것으로 보지 않으며, target 노드를 실제로 읽었을 때 즉시 판별한다고 가정한다. 모든 target을 읽으면 탐색을 종료한다. 대체 구현 지점은 기준선에서 고려하지 않는다.

종료 조건은 오라클이다. 에이전트가 일부만 찾고 멈추는 조기 종료는 종료 규칙이 아니라 관측 축으로 표현한다. 에이전트가 완료를 믿는 시점을 모델링하는 것은 비결정적이므로 분석 범위 밖이다.

선택된 정책은 최소·기대·최대 세 비용 시나리오에 공통으로 적용한다. 세 시나리오는 그 정책이 허용하는 query와 결과의 선택 순서만 다르다.

읽은 노드의 재방문은 지원하되 초기 확률은 0이다. 추후 실제 에이전트 로그로 재방문 확률을 정하며, 재방문은 기대 비용 simulation에만 반영한다.

## 비용 계약

비용은 원래 축과 경로 선택용 가중 비용을 함께 제공한다.

- 탐색 turn
- search tool call
- read tool call
- query 결과 token
- readable node token
- 0-result query 수
- 재방문 횟수
- 노출된 비타겟 후보와 중복 occurrence

0-result query는 결과 token과 비타겟 노출이 0이지만 turn과 search tool call을 소모한다. 별도 축으로 두지 않으면 저장소에 없는 단어를 만들어내는 seed query의 품질이 비용에 나타나지 않는다.

다음은 비용이 아니라 조기 종료 위험의 관측값이다. 오라클 종료를 유지하면서 누락 위험을 사후 도출하기 위한 것이므로 weighted cost에는 넣지 않는다.

- target별 발견 turn 인덱스
- 검색 결과에 노출됐으나 읽지 않은 target 수
- hint를 받았으나 읽지 않은 노드 수

재방문 횟수 축은 재방문 확률이 0인 기준선에서 항상 0이다. 최소 비용과 BFS 최대 비용은 정의상 재방문을 반영하지 않고, 기대 비용은 반영하지만 확률이 0이므로 표본에 나타나지 않는다. 실제 에이전트 로그로 확률을 정한 뒤에 값을 갖는 자리표시자로 취급한다.

가중 비용은 여러 축을 하나의 저장소 점수로 축약하기 위한 값이 아니라, 하나의 탐색 경로를 선택하기 위한 목적 함수다. 초기에는 명시적으로 임시인 기본 weight profile을 사용하고 모든 원래 비용 축과 weight를 함께 출력한다.

weight 값은 계약 문서나 코드 상수가 아니라 저장소 안의 버전 관리되는 profile 파일에 둔다. 비용 weight profile과 verification accessibility weight를 같은 방식으로 관리하며, 모든 결과에 사용한 profile id와 버전을 기록한다. 임시 값의 교체는 profile 파일의 변경 이력으로 추적하고, 교체 전후 비용은 같은 graph에서 비교한다.

### 토크나이저

token 비용은 문자 수 × 3으로 근사한다. 숫자는 이 근사에서 제외하고 통용되는 숫자 토크나이저 방식으로 센다.

### 최소 비용

결과 그룹 소진 규칙을 지키는 경로 중 임시 weight profile의 가중합이 가장 작은 target 도달 경로다. 가중합이 동률인 경로는 다음 사전식 cascade로 처리한다.

1. 원 비용 축의 사전식 비교. 축 우선순위는 profile 파일에 명시하며 weight와 별개로 고정한다. weight를 교체해도 tie-break가 흔들리지 않아야 profile 교체 전후의 비용 비교가 의미를 갖는다.
2. 경로 길이가 짧은 쪽.
3. id 시퀀스의 사전식 최소. id는 정규화된 저장소 상대 경로와 qualified symbol name의 조합이며 구분자를 정규화하고 바이트 순서로 비교한다. 파일시스템 열거 순서나 해시에 의존하면 M1의 결정적 serialization이 깨진다.

tie-break 규칙에도 버전을 붙여 결과에 기록하고 M1의 결정성 테스트 범위에 포함한다.

weight가 명시적으로 임시인 동안 동률은 흔하다. 최소 경로 하나만 출력하면 M4의 병목 귀속이 실제 경로 집중인지 tie-break의 우연인지 구분되지 않으므로, 동률 경로의 개수를 함께 출력하고 병목 귀속은 동률 경로 집합 전체를 근거로 한다. 동률 경로 열거는 최악의 경우 지수적이므로 열거 상한을 profile에 두고, 상한을 넘으면 절단 여부를 표시해 귀속이 표본 기반임을 결과에 명시한다.

### 기대 비용

결과 그룹 소진 규칙 안에서 매 단계 가능한 query와 결과 순서를 표본으로 뽑은 Monte Carlo simulation의 평균이다.

결과 노드의 선택 순서는 hint에 기반한 결정적 prior로 가중한다. 선언 occurrence를 사용 occurrence보다 먼저 읽고, 파일명 완전 일치를 우선하며, 테스트를 후순위로 두는 행동은 검색 시점에 이미 비용을 지불한 정보만으로 재현할 수 있다. 이 정보를 버리고 균등 무작위만 쓰면 기대 비용이 실제보다 비관적으로 치우친다.

prior는 아직 보정되지 않은 행동 모델이므로 균등 무작위 정책을 함께 유지한다. `uniform`과 `hint-prior`를 profile의 이름 있는 정책으로 두고 결과에 사용한 정책을 기록하면, prior의 효과 자체가 두 실행의 차이로 관측되고 반증 가능해진다. 기본값은 `hint-prior`이며 prior weight는 M6의 보정 대상이다.

prior는 표본 분포만 바꾸고 최소와 최대는 같은 순서 공간의 극값이므로 `최소 ≤ 기대 ≤ 최대`는 유지된다.

최소 표본 수, 수렴 조건, 최대 표본 수를 두며 random seed, 실제 표본 수, 표준오차와 신뢰구간을 기록한다. 기본값과 허용 오차는 fixture와 실제 저장소 분석으로 조정한다.

### 최대 비용

BFS queue 규칙을 유지하면서 query와 결과 그룹의 가능한 순서를 가장 불리하게 선택했을 때의 비용이다. `query → read`는 depth 1이며 구조적 최대 비용에는 재방문을 넣지 않는다.

### 도달 실패

근사 graph에서 모든 target에 도달하지 못할 수 있다. 이 경우 비용에 임의의 패널티를 넣지 않고 실패 상태와 도달하지 못한 target을 명시한다. 실패한 query, 부분 발견 target을 포함한 상세 실패 출력은 M2의 출력 계약에서 정의한다.

세 비용은 같은 weight profile, 동일한 graph와 동일한 exploration policy 위에서 순서 선택만 달리한다. 따라서 재방문 확률이 0인 동안에는 `최소 ≤ 기대 ≤ 최대`가 성립한다. 재방문 확률을 0보다 크게 두면 기대 비용이 BFS 최대 비용을 넘을 수 있으므로 그 시점에 순서 계약을 다시 정한다. 각 결과에는 사용한 탐색 정책과 재방문 확률을 명시한다.

## Zone of effect

potential zone of effect는 target 변경의 영향을 받을 수 있어 에이전트가 읽고 검증해야 하는 전체 후보 범위다. 호출자, 소비자, importer, type user, 상속·구현체, route, 설정 소비자, read/write 사용자와 관련 문서 등을 관계 의미에 맞는 방향으로 전파한다.

zone의 각 노드에는 다음 정보를 기록한다.

- target에서 이어지는 잠재 영향 경로
- 관계 종류와 방향
- 근거가 된 code, query, framework rule 또는 문서 mention
- 정적 분석 신뢰도와 한계
- verification accessibility 구성값
- 사용자 cutoff 안에 포함되었는지 여부

verification accessibility는 자료 종류, 관계 종류, 거리와 정적 신뢰도 등의 가중합으로 정렬한다. 이는 실제 영향의 중요도나 변경 필요성 점수가 아니다. 낮은 접근성 때문에 cutoff 밖에 있더라도 potential zone에서 제거하지 않으며, `영향 가능성이 있으나 이번 검증 시나리오에서 미관측`으로 보고한다.

사용자 cutoff의 기본 입력 방식과 가중치는 실제 AI 활용이 활발한 공개 저장소를 분석한 뒤 정한다. 테스트는 potential zone에 항상 포함하되 verification accessibility 순위와 cutoff 결과에서 기본 제외하며, 설정으로 포함할 수 있다. 저장소별 문서 관리 정책과 연동한 policy zone은 현재 milestone 밖의 아이디어다.

## Task-less graph-wide 분석

task가 없어도 저장소 자체를 분석한다. 모든 readable node를 잠재 target으로 보고 다음 결과를 지표별로 제공한다.

- PageRank, 중심성, 연결 컴포넌트와 k-hop 비용
- 큰 potential zone을 만드는 target
- 읽어야 하지만 verification accessibility가 낮은 노드와 subgraph
- cycle, bridge, articulation과 과도한 query 분기
- unresolved 또는 dynamic boundary
- exact query에서 비타겟 후보가 과도하게 노출되는 지점
- 비정상적으로 크거나 단절된 subgraph

전역 단일 품질 점수는 만들지 않는다. 결과는 관련 노드, query, edge, 경로, 비용 구성과 불확실성으로 역추적할 수 있어야 한다.

## 평가 시나리오 생성

graph-wide 분석에서 문제가 될 소지가 높은 target을 선정하고, sLLM이 target 정보를 입력받아 자연어 task를 생성한다. 예를 들어 `SettingsTab.kt`와 `AudioSettingDialog`가 target이라면 `오디오 출력 변경 UI를 수정하라`와 같은 task를 만들 수 있다.

- 같은 target에 여러 task를 생성한다.
- 쉬운 시나리오는 파일명이나 identifier를 직접 포함할 수 있다.
- target identifier가 없는 task를 최소 하나 포함한다.
- 생성 task는 결과 metadata에서 합성 시나리오임을 명시한다.
- task를 받은 seed-query 생성 sLLM에는 target이나 graph를 제공하지 않는다.
- 고의로 잘못된 target을 지시하는 시나리오는 만들지 않는다.

합성 task는 실제 사용자 task라고 주장하기 위한 것이 아니라 동일 target이 task 표현에 따라 얼마나 다르게 발견되는지 평가하기 위한 것이다.

## 구조적 병목과 개선 후보

병목은 다음 근거 중 하나 이상으로 설명한다.

- target 또는 zone에 도달하는 유효 경로가 집중되는 node, query 또는 edge
- 비타겟 결과를 많이 노출해 기대·최대 비용을 높이는 query
- exact query 없이는 발견하기 어려운 search-only 관계
- 코드, 설정, 문서와 테스트가 멀리 분산된 관계
- 결과에 노출되거나 hint를 남겼지만 반복적으로 읽히지 않는 노드
- 낮은 verification accessibility 때문에 확인에서 누락되기 쉬운 잠재 영향 노드
- 여러 target 또는 zone에서 반복되는 공통 병목
- 제거하거나 비용을 낮췄을 때 탐색 비용이 감소하는 대상

개선 후보는 실제 변경 없이 graph를 제한적으로 수정한 what-if 결과로 비교한다. 비용 감소, 영향을 받는 target 수와 예측 신뢰도를 분리해 제공한다.

## 로드맵

각 마일스톤은 자기 결과의 출력 스키마와 역추적 근거 필드를 함께 정의하고 완료 조건에 포함한다. 출력 계약을 따로 모으는 마일스톤은 두지 않는다.

기존 구현의 완료 표시는 새 분석 계약에 대한 완료를 뜻하지 않는다. 현재 코드는 언어·프레임워크 graph, graph metric과 구조적 마찰 진단을 포함한다. 이전 계약의 exploration cost, task difficulty, 저장소 cost diff와 git diff 영향 분석은 새 query 행동 모델·비용 의미와 맞지 않아 제거했다.

### M0. 문서와 계약 재정렬 — 진행 중

- 프로젝트 목적, graph 경계와 비목표 확정
- query group, 탐색 turn, 비용 축과 세 비용 계약 문서화
- zone of effect와 verification accessibility 분리

완료 조건: 모든 기준 문서가 동일한 목적과 용어를 사용하고, 기존 기능마다 유지·교체·제거 상태가 지정된다.

### M1. Agent-view graph

- readable node와 query node 모델
- 파일 token 임계 기반 read 단위 분할
- 파일 내용과 경로 이름공간을 포함한 검색 surface, list query
- exact query 추출
- 버전 관리되는 규칙표 기반 derived query 생성
- 유일 특정·후보 축소로 구분한 연결. import·qualified name 해석과 framework connection을 같은 속성으로 처리
- 코드·문서·주석 occurrence 및 연결 근거
- 고정된 출력 형식 위의 occurrence hint 엣지
- hint 기반 read 없는 query 생성과 상한
- refinement query와 깊이·후보 수 상한
- query 동등성, 중복 실행 억제
- 진입 문서 처리와 자동 주입 표시
- query 결과 그룹과 raw output 비용
- 결정적인 graph serialization과 diff

완료 조건: 동일 저장소와 설정에서 같은 query group, 결과, 근거와 비용을 재현한다. read 단위 분할, hint 투영과 query 동등성 규칙이 재현성 테스트에 포함된다.

### M2. Target discovery cost

- 명시적 query와 sLLM 생성 최초 query 집합
- sLLM model revision, prompt, decoding 설정의 주입과 기록
- 파라미터화된 exploration policy, 기본값 `bfs-exhaust`
- 결과 그룹 소진 및 대기 query 동작
- 버전 관리되는 profile 파일의 임시 weighted cost profile
- 버전이 붙은 tie-break cascade와 동률 경로 개수 출력
- `uniform`과 `hint-prior` 결과 순서 정책
- weighted minimum, Monte Carlo expected, BFS maximum
- 0-result query, 발견 turn 인덱스, 미독 target·hint 관측 축
- 다중 target 전체 발견 종료와 unreachable 처리
- 실제 에이전트 행동 검증을 위한 trace schema

완료 조건: 계약 fixture에서 탐색 상태 전이와 비용 축이 일치하고, MC 결과가 기록된 오차 범위 안에서 재현된다. 정책과 tie-break 버전이 다른 결과는 서로 비교하지 않고 각각 재현된다.

### M3. Zone of effect and verification accessibility

- 관계별 잠재 영향 전파
- 버전 관리되는 profile 파일의 accessibility weight
- 전체 potential zone과 accessibility 순위
- 사용자 cutoff와 미관측 영향 후보
- 테스트 기본 제외 및 설정 포함
- zone 확인 비용과 근거 경로

완료 조건: target별 전체 zone, cutoff 결과와 접근성 근거가 분리되어 재현된다.

### M4. Graph-wide bottleneck analysis

- graph metric과 potential zone 집계
- query branching, refinement 연쇄, candidate dilution과 search-only 관계
- cycle, bridge, articulation, unresolved boundary와 abnormal subgraph
- target 발견 병목과 zone 검증 병목 분리
- 병목 제거·완화의 반사실 비용 비교

완료 조건: 각 병목이 어떤 target 또는 zone의 어떤 비용 축을 높이는지 경로와 what-if 결과로 설명한다.

### M5. Generated evaluation scenarios

- 문제가 될 소지가 높은 target 선정
- target별 복수 자연어 task 생성
- identifier 포함·미포함 난이도 변형
- M2의 sLLM 실행 계약을 재사용한 task-only seed query 생성과 합성 metadata
- 실제 공개 저장소 및 고정 fixture 평가

완료 조건: 동일 모델 revision과 설정에서 task와 최초 query를 재현하고, 표현 차이에 따른 발견 비용을 비교한다.

### M6. Calibration and operation — 보류

- 실제 AI agent tool/read trace 기반 행동 모델 보정
- temporary weight와 zone accessibility weight 조정
- zone cutoff 기본 입력 결정
- 추가 언어·프레임워크 adapter
- 대규모 graph 성능 예산
- 검증 dataset 버전 관리와 회귀 평가

완료 조건: 보정 데이터, 모델·도구 설정과 평가 절차가 버전 관리되고 기존 계약 fixture를 유지한다.

## 검증 원칙

- graph가 표현하는 관측 가능성과 표현하지 못하는 의미 추론을 구분한다.
- sLLM이 받은 입력, model revision, prompt와 decoding 설정을 기록한다.
- 합성 task와 실제 task를 구분한다.
- time, randomness, model, tool 설정을 주입하고 random seed를 기록한다.
- Monte Carlo 결과에는 표본 수와 오차를 함께 제공한다.
- 비용은 원래 축, 사용한 weight profile id와 버전, weighted 결과를 함께 제공한다.
- 사용한 exploration policy, 결과 순서 정책, tie-break 규칙 버전과 검색 출력 형식을 결과에 기록한다.
- 병목은 제거·완화 전후의 비용 변화로 검증한다.
- 모든 결과는 node, query, edge, occurrence와 경로 근거로 역추적할 수 있어야 한다.
- 실제 agent가 읽은 대상과 읽어야 했던 대상을 같은 정답으로 취급하지 않는다.

## 비목표

- task의 의미적 구현 난이도나 개발자의 숙련도를 예측하지 않는다.
- task에서 정답 target을 자동으로 확정한다고 주장하지 않는다.
- 재현 가능한 단서가 없는 LLM의 의미적 연상을 graph edge로 간주하지 않는다.
- 전통적인 코드 품질, 보안 또는 runtime 성능 분석을 대체하지 않는다.
- 동적 runtime 연결을 정적으로 완전 복원한다고 주장하지 않는다.
- 기대 비용을 특정 AI 모델의 실제 비용 예측치로 단정하지 않는다.
- potential zone을 실제 변경 영향의 확정 집합으로 주장하지 않는다.
- 여러 지표를 하나의 저장소 품질 점수나 일반적인 task difficulty 순위로 축약하지 않는다.
