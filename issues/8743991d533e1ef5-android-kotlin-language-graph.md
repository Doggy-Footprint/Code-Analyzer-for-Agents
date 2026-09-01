# Android 어댑터에 Kotlin 언어 그래프 연결

**Date:** 2026-09-01

## 문제

Android 어댑터가 만드는 그래프에는 Kotlin 언어 심볼 계층이 없다. FastAPI 트랙은 Python symbol graph 위에 프레임워크 의미를 얹지만(`framework_analyzers/fastapi/graph.py:390-395`), Android 트랙은 프레임워크가 인식한 컴포넌트만으로 그래프를 구성한다.

`examples/nowinandroid_sample`(`.kt` 142개)에서 두 경로를 각각 실행한 결과다.

| | Kotlin 노드 | 엣지(설정 제외) | 관계 종류 |
|---|---|---|---|
| `--framework android` | 65 | 56 | `CALLS` 3, `ROUTES` 18, `BINDS` 8, `PROVIDES` 6, `DEFINES_ENTITY` 6, `CONTAINS` 5, `INSTALLS_IN` 4, `INJECTS` 3, `QUERIES` 2, `USES_VIEWMODEL` 1 |
| `--language kotlin` | 468 | 4342 | `READS` 1572, `TESTS` 1053, `WRITES` 388, `CONTAINS` 354, `CALLS` 322, `TYPE_USES` 225, `IMPORTS_SYMBOL` 126, `IMPORTS` 109, `INSTANTIATES` 72, `IMPLEMENTS` 17, `INHERITS` 4 |

Android 경로에서는 파일 60개, 클래스 51개, 인터페이스 20개, 메서드 179개가 그래프에 존재하지 않는다. `TESTS` 엣지 1053개도 전부 없다 — `enrich_repository`가 테스트 노드와 프로덕션 노드를 이름으로 잇는데 이을 프로덕션 심볼 자체가 없다.

### 구조적으로 막힌 진단

`annotate_nodes`의 `node.kind = node.kind or node.category`(`language_analyzers/core/annotate.py:22`)가 kind를 `"composable"`, `"room_dao"` 같은 어댑터 어휘로 채운다. M3의 `central_large_symbol`은 `NodeKind.CLASS/FUNCTION/METHOD/FILE/MODULE`만 후보로 보므로 Android 그래프에서는 **원리적으로 한 건도 나올 수 없다**.

`cyclic_dependency`는 막혀 있지 않다. Android의 `CALLS` 엣지가 구조 관계 집합에 포함되어 탐지 자체는 동작한다. 다만 CALLS 엣지 3개짜리 그래프 위에서 도는 것뿐이다.

`missing_test_link`는 `TESTS` 엣지가 하나도 없으므로 "테스트가 없다"가 아니라 "테스트 연결을 만들 대상이 없다"를 보고하고 있다. 현재 8건이 나오지만 근거가 다르다.

### 진단 수치 비교

같은 샘플, 같은 임계값 설정에서:

| | 진단 합계 | central_large_symbol | missing_test_link | bridge_bottleneck | reexport_ambiguity | cyclic_dependency |
|---|---|---|---|---|---|---|
| `--framework android` | 8 | 0 | 8 | 0 | 0 | 0 |
| `--language kotlin` | 77 | 16 | 20 | 20 | 20 | 1 |

---

## 왜 이슈로 남기는가

1. **M3 구현 중 발견했지만 M3 범위가 아니다.** M3는 진단 계층이고, 이건 M1(그래프 완성도)에 속하는 Android 트랙 한정 결함이다. M3의 완료 조건 — 각 진단이 재현 가능한 그래프 근거를 제공하고 변경 전후 비용 변화를 보여 준다 — 은 Python/Kotlin/TypeScript 트랙에서 충족되므로 M3를 막지 않는다.
2. **결정이 필요한 항목이 있어 임의로 진행할 수 없다.** 아래 "결정이 필요한 사항" 참고. `AGENTS.md`의 User Decision 규칙에 해당한다.
3. **지금 나오는 Android 진단 수치를 다른 트랙과 비교하면 안 된다는 사실을 기록해 둘 필요가 있다.** 이 이슈가 없으면 "Android 저장소는 마찰이 적다"는 잘못된 결론이 나온다.

---

## 결정이 필요한 사항

### D1. `generated` 디렉터리 처리 (핵심)

`AndroidAnalyzer.EXCLUDED_DIRS`는 `{"build", ".gradle", ".idea", ".git", "generated"}`(`framework_analyzers/android/analyzer.py:29`), `KotlinAnalyzer._discover_files`는 `{".git", ".gradle", ".idea", "build"}`(`language_analyzers/kotlin/analyzer.py:143`)로 다르다. 병합하면 `generated/` 아래 `.kt`가 언어 그래프에만 들어온다. Room·Hilt는 코드 생성이 많은 영역이라 무시할 크기가 아니다.

| 선택지 | 결과 |
|---|---|
| (a) Kotlin 코어에도 `generated` 제외 | 두 집합이 일치. 생성 코드가 실제 연결을 매개할 때 그래프가 끊김 |
| (b) 현행 유지 (언어 그래프에만 포함) | 생성 코드가 노드로 들어오되 `flags.is_generated_path`가 잡아 비용 배수 0.1이 적용되고 M3 진단 모집단에서도 제외됨. 노드 수만 늘고 진단은 오염되지 않음 |
| (c) 어댑터도 `generated` 포함 | 프레임워크 추출이 생성 코드를 컴포넌트로 잡음. 노이즈 증가 |

### D2. `--no-language-graph`를 Android로 확장할지

현재 이 플래그는 FastAPI 전용으로 헬프에 명시되어 있고(`code_analyzer/cli.py:93-97`) Android 분기는 읽지 않는다. 확장하면 플래그 하나로 두 어댑터를 제어할 수 있고, 확장하지 않으면 Android는 항상 언어 그래프를 포함하게 된다.

### D3. `inject_field` 바인딩의 `IMPLEMENTED_BY`

`DiBindingInfo`가 소유 클래스명을 필드로 갖고 있지 않아 이 유형만 대상 심볼 id를 계산할 수 없다. 모델에 필드를 추가할지, 이 유형만 `IMPLEMENTED_BY`를 생략할지 결정이 필요하다.

### D4. `.kt` 이중 파싱 허용 여부

`AndroidAnalyzer`와 `KotlinAnalyzer`가 같은 파일을 각각 tree-sitter로 파싱한다. FastAPI도 같은 구조(`PythonSourceAnalyzer`를 어댑터와 언어 코어가 각각 실행)이므로 선례에 어긋나지는 않으나, 큰 프로젝트에서는 드러난다. 파서 캐시 공유를 이 작업에 포함할지 별도로 둘지 결정이 필요하다.

---

## 작업 완료 시 예상 결과

- Android 그래프의 Kotlin 노드가 65 → 약 468, 엣지가 56 → 약 4400으로 늘어난다.
- `central_large_symbol`이 동작하기 시작한다(같은 샘플 기준 16건).
- `TESTS` 엣지가 생기면서 `missing_test_link`의 근거가 "연결할 대상이 없음"에서 "테스트가 없음"으로 바뀐다.
- 프레임워크 컴포넌트에서 구현 심볼로 `IMPLEMENTED_BY` 엣지가 생겨, Composable/DAO/ViewModel에서 실제 코드로 탐색이 이어진다.

### 부작용

- **betweenness 전략 전환**: 노드가 500(`exact_betweenness_threshold`)을 넘겨 `exact` → `deterministic_sampled`로 바뀐다. 값이 근사가 되므로 `bridge_bottleneck` 결과를 이전 실행과 직접 비교할 수 없다. `betweenness_strategy`가 리포트에 남으므로 해석은 가능하다.
- **비용 diff 단절**: Room query·Composable 노드 id에 줄 번호가 박혀 있어(`query_{...}_{line}`, `composable_{...}_{line}`) 언어 그래프 도입 전후의 두 export를 `--baseline`으로 비교하는 것은 의미가 없다.

---

## 작업 범위

### A. `KotlinAnalyzer`에 `build()` 분리

유일하게 실질적인 리팩터링이다. `PythonGraphAnalyzer`는 `analyze()`와 `build(sources) -> (nodes, edges)`로 이미 나뉘어 있어 어댑터가 `build`만 부른다(`language_analyzers/python/graph.py:148,170`). `KotlinAnalyzer.analyze()`는 파싱·심볼 수집·노드/엣지 구성·git diff·`enrich_repository`·stats·컬렉션을 한 메서드에서 처리한다(`language_analyzers/kotlin/analyzer.py:50-92`). 파일 순회부터 `_add_symbol_edges` 루프까지(`:53-75`)를 `build()`로 잘라내고 나머지는 `analyze()`에 남긴다. Kotlin은 소스 파싱이 `build` 안에 있으므로 인자 없는 `build()`가 된다.

이 분리는 `enrich_repository` 이중 호출 문제도 함께 해소한다 — Android 빌더가 이미 호출하므로(`framework_analyzers/android/graph.py:285`) `analyze()`를 그대로 부르면 두 번 돈다.

### B. `AndroidArchitectureGraphBuilder` 병합

`framework_analyzers/android/graph.py:280-282`의 `annotate_nodes` / `mark_edges` 직후, `arch.nodes = nodes` 직전에 FastAPI와 같은 순서로 삽입한다.

```python
annotate_nodes(nodes, arch.project_path, "android", "kotlin")
mark_edges(edges, nodes=nodes)
if self.include_language_graph:
    language_nodes, language_edges = KotlinAnalyzer(arch.project_path).build()
    known = {node.id for node in nodes}
    nodes.extend(node for node in language_nodes if node.id not in known)
    edges.extend(language_edges)
    edges.extend(self._implementation_edges(arch, {node.id for node in nodes}))
```

**이 순서가 계약이다.** `mark_edges`는 넘겨받은 모든 엣지의 `confidence`를 `FRAMEWORK_INFERRED`, `resolution`을 `UNIQUE_NAME`으로 덮어쓴다(`language_analyzers/core/annotate.py:52-56`). 언어 엣지를 먼저 합치면 Kotlin 코어가 구분한 `static_certain`/`ambiguous`/`unresolved`가 지워지고, M1의 신뢰도 계약과 M3의 `reexport_ambiguity`·`evidence_gap`이 동시에 무의미해진다. 같은 이유로 `annotate_nodes`도 언어 노드에 닿으면 안 된다(이미 typed span/cost를 갖고 있다).

노드 id는 충돌하지 않는다(Android는 `composable_...`, Kotlin은 `kotlin:...`). `known` 필터는 방어용으로 유지한다.

### C. `IMPLEMENTED_BY` 매핑

Kotlin 심볼 id는 `kotlin:{파일경로}#{qualname}`이고 qualname은 중첩 스코프를 점으로 이은 것이다(`language_analyzers/kotlin/analyzer.py:186-188`). Android 컴포넌트의 `module` 필드가 프로젝트 루트 기준 상대 경로다(`framework_analyzers/android/analyzer.py:80-84`).

| 컴포넌트 | 대상 qualname | 소유자 이름 출처 |
|---|---|---|
| Composable | `{name}` | `ComposableInfo.name` |
| ViewModel / Room Entity / DAO / Database / DI Module / Dagger Component / Retrofit API / Activity·Fragment | `{name}` | 각 `*Info.name` |
| Room query method | `{DAO명}.{메서드명}` | `RoomDaoInfo.name` + `RoomQueryMethodInfo.name` |
| Retrofit endpoint | `{API명}.{메서드명}` | `RetrofitApiInfo.name` + `RetrofitEndpointInfo.name` |
| DI binding (`provides`/`binds`) | `{모듈클래스명}.{메서드명}` | `owner_module_id` → `DiModuleInfo.name` |
| DI binding (`inject_constructor`) | `{클래스명}` | `DiBindingInfo.injected_type` |
| DI binding (`inject_field`) | — | D3 참고 |

주의: **하위 컴포넌트 모델은 소유자 이름을 필드로 갖고 있지 않다.** `RoomQueryMethodInfo.name`은 메서드명뿐이고(`framework_analyzers/android/analyzer.py:223-224`), `DiBindingInfo.name`도 메서드명이다(`:286-287`). 소유자 이름은 id 문자열 안에만 있으므로 id를 파싱하지 말고 부모 객체를 순회하며(`for d in arch.room_daos: for m in d.methods:`) 쌍을 만들어야 한다.

**경로 구분자**: Android는 `str(file_path.relative_to(project_path))`(OS 구분자), Kotlin은 `.as_posix()`를 쓴다. macOS/Linux에서는 같지만 Windows에서는 대상 id가 전부 빗나간다. 매핑 시 `Path(module).as_posix()`로 정규화해야 한다.

### D. CLI

D2 결정에 따라 `AndroidArchitectureGraphBuilder(include_language_graph=not args.no_language_graph)`를 넘기고 헬프 문구에서 `[fastapi only]`를 제거한다. `parse_args`의 교차 검증(`code_analyzer/cli.py:129`)은 이 플래그를 다루지 않으므로 변경 불필요.

---

## 테스트

`tests/test_android_analyzer.py`의 관례(임시 디렉터리에 `.kt` 인라인 작성, `@unittest.skipUnless(_HAS_TREE_SITTER, ...)`)를 따른다.

- `build()`가 `analyze()`와 동일한 노드/엣지를 내는지 — 리팩터링 무손실 검증
- 병합 후 언어 엣지의 `confidence`/`resolution`이 보존되는지 — `mark_edges` 순서 회귀를 잡는 유일한 테스트
- 컴포넌트 유형별 `IMPLEMENTED_BY` 대상 id가 실재 Kotlin 노드를 가리키는지, 특히 DAO 메서드·Retrofit 엔드포인트 같은 중첩 심볼
- `--no-language-graph`가 Android에서 언어 노드를 제외하는지 (D2가 확장으로 결정될 경우)
- `tests/test_android_analyzer.py:499`의 실샘플 스모크 테스트가 여전히 모든 엣지 끝점이 실재 노드를 가리키는지 확인 — 병합 버그를 가장 싸게 잡는 테스트

검증은 `--framework android --diagnostics` 결과의 `central_large_symbol`이 0이 아니게 되는지, 노드 수가 `--language kotlin` 결과에 근접하는지로 한다.

## 규모 견적

`KotlinAnalyzer.build()` 분리 약 40줄, Android 빌더 병합 5줄, `_implementation_edges` 약 60줄, CLI 3줄, 테스트 약 150줄. 코드는 작고 실제 시간은 D1 결정과 중첩 심볼 id 매핑 검증에 들어간다.
