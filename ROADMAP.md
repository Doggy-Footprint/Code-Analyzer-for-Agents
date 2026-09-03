# Goal: AI Agent Repository Exploration Analyzer

## 목적

이 프로젝트는 AI 코딩 에이전트가 저장소에서 변경 대상을 찾고, 그 변경이 영향을 줄 수 있는 범위를 확인하는 과정을 정적 그래프로 근사한다. 분석기는 다음 질문에 답한다.

- 에이전트가 task를 받고 target을 발견하려면 무엇을 검색하고 얼마나 읽어야 하는가?
- target을 수정하기 전에 어디까지 읽고 검증해야 하는가?
- 필요한 대상이 존재하지만 검색 후보에 묻히거나 연결이 약해 놓치기 쉬운 지점은 어디인가?
- 어떤 노드·엣지·subgraph가 탐색 turn, tool call, token 소비를 증가시키는가?
- 저장소 구조를 어떻게 바꾸면 이 비용과 누락 위험을 줄일 수 있는가?

그래프는 저장소의 의미를 완전히 복원하지 않는다. 에이전트가 코드·문서·주석에서 얻을 수 있는 명시적 단서, 정확 검색, 정적 관계, 확정 가능한 프레임워크 규칙을 모델링한다. 코드를 읽고 의미상 비슷한 표현을 떠올리는 것처럼 재현 가능한 단서가 없는 추론은 분석 범위에서 제외한다. 따라서 결과는 AI 에이전트 관점에서 본 저장소의 결정적 근사다.

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

## 그래프 모델

그래프는 저장소 엔티티뿐 아니라 탐색 행동을 표현한다.

### Readable nodes

파일, 모듈, 클래스, 함수, 메서드, 타입, 설정, 테스트, 문서, API endpoint 등 에이전트가 읽을 수 있는 대상을 표현한다. 실제 read 범위의 근사 방식은 [IDEA.md](IDEA.md)의 검증 항목으로 관리한다.

### Query nodes and result groups

query node는 동일한 탐색 행동으로 한 번에 노출되는 결과 그룹을 표현한다. query 후보는 다음 명시적 단서에서 생성한다.

- identifier와 qualified name
- 문자열 리터럴
- 파일·모듈 경로
- 설정 키
- URL과 route
- 오류 메시지
- 문서 및 주석에 코드 형태로 적힌 표현
- 확정 가능한 프레임워크 연결

확정 가능한 프레임워크 연결은 static connection과 동일하게 취급하며, 에이전트가 symbol 또는 정확한 표현으로 검색해 이동할 수 있어야 한다. 정확 검색은 코드·문서·주석 전체를 대상으로 한다. 고유 도착 노드가 50개를 초과하는 query는 일반어로 간주해 제외한다. 정확 검색 결과가 없을 때에만 약한 자연어 표현과 확정할 수 없는 프레임워크 추론을 fallback 후보로 고려한다.

검색 occurrence는 독립 readable node로 만들지 않는다. occurrence는 query 결과의 근거이며 실제 도착점은 enclosing readable node다. query 출력 비용은 실제 검색 결과의 모든 occurrence를 기준으로 계산한다.

### 탐색 범위의 한계

분석기는 다음 행동을 일반 탐색 연결로 만들지 않는다.

- 현재까지 읽은 내용에 없는 표현을 의미적으로 연상하는 행동
- 저장소 외부 지식만으로 만들어진 비결정적 검색어
- 실제 에이전트가 사용할 수 없는 analyzer 내부 정보로 target을 직접 선택하는 행동

분석 가능한 직접 연결이 없고 특정 exact query를 실행해야만 발견되는 관계는 별도 진단 후보다.

## Target 발견 모델

### 최초 query 생성

명시적 seed query가 없으면 Qwen3.5-4B를 탐색 모방용 sLLM으로 사용한다. sLLM은 task만 입력받고 최초 검색어 집합을 생성한다. 저장소 파일 목록, graph 또는 정답 target은 제공하지 않는다. 생성된 검색어는 하나의 최초 미실행 query 집합으로 사용하며, 검색어별 독립 시나리오로 분리하지 않는다.

모델 revision, prompt, decoding 설정과 생성 결과를 기록한다. 생성 query는 target 예측이 아니라 에이전트의 첫 검색 행동을 재현하기 위한 입력이다.

### 한 탐색 turn

1. 아직 실행하지 않은 query 중 하나를 선택한다.
2. query 결과 전체를 노출하고 모든 raw occurrence의 출력 token 비용을 기록한다.
3. 고유 도착 노드의 순서를 정한다.
4. 결과 노드를 하나씩 읽는다.
5. 읽은 노드에서 생성된 새 query는 현재 결과 그룹을 모두 확인할 때까지 대기시킨다.
6. 현재 그룹을 소진하면 대기 중인 query에서 다음 query를 선택한다.

`query → result 선택 → read`를 graph depth 1의 탐색 turn으로 본다. query와 read의 tool call 및 token 비용은 별도 축으로 기록한다. 검색 결과에 target이 나타난 것만으로는 발견한 것으로 보지 않으며, target 노드를 실제로 읽었을 때 즉시 판별한다고 가정한다. 모든 target을 읽으면 탐색을 종료한다. 대체 구현 지점은 기준선에서 고려하지 않는다.

읽은 노드의 재방문은 지원하되 초기 확률은 0이다. 추후 실제 에이전트 로그로 재방문 확률을 정하며, 재방문은 기대 비용 simulation에만 반영한다.

## 비용 계약

비용은 원래 축과 경로 선택용 가중 비용을 함께 제공한다.

- 탐색 turn
- search tool call
- read tool call
- query 결과 token
- readable node token
- 재방문 횟수
- 노출된 비타겟 후보와 중복 occurrence

가중 비용은 여러 축을 하나의 저장소 점수로 축약하기 위한 값이 아니라, 하나의 탐색 경로를 선택하기 위한 목적 함수다. 초기에는 명시적으로 임시인 기본 weight profile을 사용하고 모든 원래 비용 축과 weight를 함께 출력한다.

### 최소 비용

임시 weight profile의 가중합이 가장 작은 target 도달 경로다. 동일 비용의 경로는 결정적인 tie-break 규칙으로 처리한다.

### 기대 비용

매 단계 가능한 query와 query 결과 순서를 무작위로 선택한 Monte Carlo simulation의 평균이다. 최소 표본 수, 수렴 조건, 최대 표본 수를 두며 random seed, 실제 표본 수, 표준오차와 신뢰구간을 기록한다. 기본값과 허용 오차는 fixture와 실제 저장소 분석으로 조정한다.

### 최대 비용

BFS queue 규칙을 유지하면서 query와 결과 그룹의 가능한 순서를 가장 불리하게 선택했을 때의 비용이다. `query → read`는 depth 1이며 구조적 최대 비용에는 재방문을 넣지 않는다.

### 도달 실패

근사 graph에서 모든 target에 도달하지 못할 수 있다. 이 경우 비용에 임의의 패널티를 넣지 않고 실패 상태와 도달하지 못한 target을 명시한다. 상세 실패 출력 계약은 [IDEA.md](IDEA.md)에서 추후 확정한다.

세 비용은 같은 weight profile과 동일한 graph에서 서로 다른 탐색 기준을 비교한다. BFS 최대 비용은 unrestricted random exploration의 수학적 상한이 아닐 수 있으므로 현재 계약은 `최소 ≤ 기대 ≤ 최대`를 보장하지 않는다. 각 결과에는 사용한 탐색 정책을 명시한다.

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

사용자 cutoff의 기본 입력 방식과 가중치는 실제 AI 활용이 활발한 공개 저장소를 분석한 뒤 정한다. 테스트는 기본 제외하며 설정으로 포함할 수 있다. 저장소별 문서 관리 정책과 연동한 policy zone은 현재 milestone 밖의 아이디어다.

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
- 낮은 verification accessibility 때문에 확인에서 누락되기 쉬운 잠재 영향 노드
- 여러 target 또는 zone에서 반복되는 공통 병목
- 제거하거나 비용을 낮췄을 때 탐색 비용이 감소하는 대상

개선 후보는 실제 변경 없이 graph를 제한적으로 수정한 what-if 결과로 비교한다. 비용 감소, 영향을 받는 target 수와 예측 신뢰도를 분리해 제공한다.

## 로드맵

기존 구현의 완료 표시는 새 분석 계약에 대한 완료를 뜻하지 않는다. 현재 코드는 언어·프레임워크 graph, graph metric, 기존 exploration cost와 task difficulty 기능을 포함하지만, 새 query 행동 모델과 비용 의미에 맞춰 유지·교체·제거 여부를 다시 검증한다.

### M0. 문서와 계약 재정렬 — 진행 중

- 프로젝트 목적, graph 경계와 비목표 확정
- query group, 탐색 turn, 비용 축과 세 비용 계약 문서화
- zone of effect와 verification accessibility 분리
- 미확정 결정은 `IDEA.md`로 격리
- 기존 코드·테스트를 새 계약 기준으로 inventory

완료 조건: 모든 기준 문서가 동일한 목적과 용어를 사용하고, 기존 기능마다 유지·교체·제거 상태가 지정된다.

### M1. Agent-view graph

- readable node와 query node 모델
- exact query 추출과 고유 도착 노드 50개 제한
- 코드·문서·주석 occurrence 및 framework connection 근거
- query 결과 그룹과 raw output 비용
- 결정적인 graph serialization과 diff

완료 조건: 동일 저장소와 설정에서 같은 query group, 결과, 근거와 비용을 재현한다.

### M2. Target discovery cost

- 명시적 query와 sLLM 생성 최초 query 집합
- 결과 그룹 소진 및 대기 query 동작
- 임시 weighted cost profile
- weighted minimum, Monte Carlo expected, BFS maximum
- 다중 target 전체 발견 종료와 unreachable 처리
- 실제 에이전트 행동 검증을 위한 trace schema

완료 조건: 계약 fixture에서 탐색 상태 전이와 비용 축이 일치하고, MC 결과가 기록된 오차 범위 안에서 재현된다.

### M3. Zone of effect and verification accessibility

- 관계별 잠재 영향 전파
- 전체 potential zone과 accessibility 순위
- 사용자 cutoff와 미관측 영향 후보
- 테스트 기본 제외 및 설정 포함
- zone 확인 비용과 근거 경로

완료 조건: target별 전체 zone, cutoff 결과와 접근성 근거가 분리되어 재현된다.

### M4. Graph-wide bottleneck analysis

- graph metric과 potential zone 집계
- query branching, candidate dilution과 search-only 관계
- cycle, bridge, articulation, unresolved boundary와 abnormal subgraph
- target 발견 병목과 zone 검증 병목 분리
- 병목 제거·완화의 반사실 비용 비교

완료 조건: 각 병목이 어떤 target 또는 zone의 어떤 비용 축을 높이는지 경로와 what-if 결과로 설명한다.

### M5. Generated evaluation scenarios

- 문제가 될 소지가 높은 target 선정
- target별 복수 자연어 task 생성
- identifier 포함·미포함 난이도 변형
- task-only seed query 생성과 합성 metadata
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
- 비용은 원래 축, weight profile과 weighted 결과를 함께 제공한다.
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

## 보류된 결정

아직 확정하지 않은 설계와 확장 아이디어는 [IDEA.md](IDEA.md)에서 관리한다.
