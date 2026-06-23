# LKD-KGC — 지식 의존성 파싱 기반 도메인 특화 KG 구축

> 출처: *LKD-KGC: Domain-Specific KG Construction via LLM-driven Knowledge Dependency Parsing*, arXiv:2505.24163, Sun 외, EDBT 2026 제출.

## 1. 한 줄 요약
**사전 정의 스키마도, 외부 참조 KB도 없이** 도메인 지식그래프를 만든다: 문서 간 *지식 의존성*을 추론하고, 의존성 순서대로 읽으며, 엔티티 타입 스키마를 자기회귀적으로 키우고(동의어 라벨은 클러스터링으로 병합), 그 유도된 스키마가 엔티티·관계 추출을 가이드한다.

## 2. 핵심 아이디어
- **문서는 독립적이지 않다.** 스키마 가이드 KGC는 보통 문서를 따로따로 처리하지만, 도메인 코퍼스에는 구조가 있다 — "Sensors" 노트는 그것을 인용하는 "Operating Procedure" 노트의 선행 조건이다. LKD-KGC는 이 순서를 명시적으로 만든다.
- **지식 의존성 파싱.** 코퍼스 위에 방향성 의존성 그래프를 추론한다 — 문서 *A가 B에 의존*하는 것은 A의 본문이 B를 참조할 때(여기서는 B의 제목을 언급할 때)다. 사이클은 결정론적으로 끊어 DAG로 만든다.
- **읽기 순서 우선순위.** 의존성 DAG의 위상 정렬로 처리 순서를 정해, 그것에 기대는 문서보다 기초 문서를 먼저 읽는다(논문의 "LLM 기반 우선순위").
- **자기회귀적 스키마 유도.** 순서대로 읽으며 각 문서가 엔티티 타입 *후보*를 기여하고, 이를 정규화 후 **클러스터링**(단수화 + 동의어 병합)해 `Sensors`/`Sensor`, `Protocol`/`Procedure`가 하나의 스키마 클래스로 모인다. 문서 간 컨텍스트가 누적되어, 뒤 문서는 스키마를 초기화하지 않고 확장한다.
- **스키마 가이드 비지도 추출.** 엔티티·관계는 지금까지 유도된 정규 스키마에 대해서만 생성한다 — 수작업 스키마도, 공개 도메인 참조 KB도 없다.

## 3. 구축 과정 (단계별)
1. **코퍼스 읽기** — `corpus.json`(`domain`, `id`·`title`·`text`를 갖는 `documents` 목록).
2. **의존성 파싱** — `title(B)`가 `text(A)`에 나타나면 간선 `B → A` 추가; 사이클은 (낮은 id 우선) 끊어 DAG 보장.
3. **읽기 순서 결정** — id 타이브레이크가 있는 Kahn 위상 정렬.
4. **자기회귀적 스키마 유도** — 읽기 순서대로 각 문서에서 타입 후보를 뽑아 정규화·클러스터링해 스키마 클래스(`DomainEntity`의 하위 클래스)로 누적.
5. **스키마 가이드 추출** — 각 문서 안에서 유도 스키마에 맞는 멘션을 타입화하고, 한 문장 + 관계 동사를 공유하는 엔티티 쌍을 연결.
6. **출력** — `ontology.ttl`(OWL 클래스 + `owl:ObjectProperty` + 타입화 개체), `ontology.json`(Cytoscape; 인스턴스 노드에 `provenance`=출처 문서), `steps.json`(문서당 스냅샷, UI 재생용).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `corpus.json` | `{"domain":..., "documents":[{"id","title","text"}, ...]}` |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf DomainEntity`, `owl:ObjectProperty`, 타입화 개체 |
| 출력 | `ontology.json` | 그래프; 인스턴스 노드에 `cls` + `provenance`(출처 문서) |
| 출력 | `steps.json` | 문서별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 사전(lexicon) 기반 결정론적 타입 후보 추출 + 결정론적 클러스터링 — 안정적 골든 파일, 키 불필요.
- `gemini`/`anthropic`/`hf_local`: LLM이 문서별 타입 후보를 제안; 의존성 파싱·읽기 순서·클러스터링·추출은 결정론으로 유지되어 그래프 형태가 안정적. 키가 없으면 자동으로 MOCK 폴백.

## 6. 사용해 보기
1. `samples/corpus.json`에서 기존 문서의 **제목**을 본문에 언급하는 문서를 추가해 새 의존성 간선을 만들고, 읽기 순서가 바뀌는 것을 확인한다.
2. 동의어(또 다른 복수형, 또는 기존 클래스로 별칭되는 라벨)를 넣어 클러스터링이 하나의 스키마 클래스로 병합하는지 본다.
3. 실행: `python pipeline.py samples runs/out --backend mock` (또는 사이트의 **Run** 버튼).
4. manifest의 `read_order`, `dependency_edges`, 그리고 `raw_type_candidates` 대 `canonical_classes`가 이 방법의 두 차별 동작에 대한 실행별 텔레메트리다.
