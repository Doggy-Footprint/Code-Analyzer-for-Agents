# Code Analyzer for AI Agents

AI 코딩 에이전트가 저장소에서 변경 대상을 찾고 영향 범위를 검증하는 과정을 정적 graph로 근사하는 analyzer다.

이 프로젝트는 일반적인 코드 품질이나 task 난이도를 점수화하지 않는다. 대신 에이전트가 실제로 사용할 수 있는 정확 검색, 코드 관계, 문서·주석 mention과 확정 가능한 framework 지식을 연결하고 다음을 분석 대상으로 삼는다.

- task에서 target을 발견하는 최소·기대·최대 탐색 비용
- target 변경 전에 읽어야 하는 potential zone of effect
- 읽어야 하지만 에이전트가 자연스럽게 발견하기 어려운 대상
- query 후보 과다 노출, search-only 관계와 구조적 병목
- 저장소 전체의 중심성, 잠재 영향 범위와 abnormal subgraph
- 병목 완화 전후의 비용 변화

## 분석 관점

graph는 AI 에이전트 관점에서 본 저장소의 근사다. identifier, literal, path, config key, URL, 오류 메시지처럼 코드와 문서에서 직접 얻을 수 있는 표현을 exact query로 만들고, 이미 읽은 identifier를 고정된 규칙표로 분해·변형한 derived query를 함께 다룬다. 동일한 검색 행동으로 노출되는 결과는 하나의 query group이다. 프레임워크 규칙으로 성립하는 연결은 규칙이 대상을 유일하게 특정하는지에 따라 무검색 이동과 query group으로 나눈다. 외부 사전이나 현재 정보에 없는 표현을 의미적으로 연상하는 행동은 재현하기 어려우므로 모델링하지 않는다.

target 발견과 zone 검증은 탐색 turn, search·read tool call, query 결과 token, readable node token 등의 원래 비용 축을 보존한다. 하나의 경로를 선택할 때에만 명시적인 weight profile을 사용한다.

## 현재 상태

언어·framework analyzer, graph metric, 구조적 마찰 진단과 renderer가 존재한다. 이전 계약의 exploration cost, task difficulty, 저장소 cost diff와 git diff 영향 분석은 새 query·비용 모델과 의미가 달라 제거했다. M2 이후의 탐색 비용과 zone of effect 구현은 아직 없다.

현재 CLI를 새 분석 계약의 안정된 인터페이스로 간주하지 않는다.

## 문서

- [ROADMAP.md](ROADMAP.md): 목적, 분석 계약, 검증 원칙과 구현 순서
- [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md): 저장소에서 작업하는 AI 에이전트의 공통 규칙
