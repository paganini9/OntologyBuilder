# OntoMetric — 2단계 검증을 갖춘 온톨로지 가이드 ESG 지표 KG 구축

> 출처: *OntoMetric: An Ontology-Driven LLM-Assisted Framework for Automated ESG Metric Knowledge Graph Generation*, arXiv:2512.01289.

## 1. 한 줄 요약
ESG 규제 문서(SASB / TCFD / IFRS S2)를, **ESGMKG 온톨로지를 강제 제약으로** 추출에 내장하고 **결정론적 식별자**를 부여하며 **2단계 검증**(의미 타입 검증 + 규칙 기반 스키마 검사)을 돌려, 페이지 단위 **출처(provenance)**를 보존하면서 거버넌스된 지표 지식그래프로 변환한다.

## 2. 핵심 아이디어
- **ESG 지표 지식은 구조적이지만 암묵적이다.** 산업·보고 프레임워크·지표 카테고리·지표·산정 모델은 구성적 의존성으로 연결되는데, 그 구조가 규제 PDF 안에 암묵적으로만 존재한다. 제약 없는 LLM 추출은 타입과 관계를 환각한다.
- **온톨로지를 일급 제약으로.** ESGMKG 스키마 — `ReportingFramework`, `MetricCategory`, `Metric`, `CalculationModel`, `Industry`와 허용 간선 `hasCategory`, `hasMetric`, `computedBy`, `appliesToIndustry` — 를 사후 참조가 아니라 추출 과정 안에 직접 작동시킨다.
- **구조 인지 분할 + 출처.** 문서를 세그먼트 단위로 순서대로 읽으며 `framework → category → metric` 컨텍스트로 구성적 중첩을 추적하고, 모든 엔티티는 원문으로 되돌아가는 페이지 단위 출처를 유지한다.
- **결정론적 식별자.** 각 엔티티에 프레임워크+카테고리+이름에서 파생한 안정적 id(`RF:`/`CAT:`/`MET:`/`CM:`/`IND:`)를 부여해 재실행·문서 간 병합이 멱등이다.
- **2단계 검증.** *1단계(의미 타입 검증)*는 제안 타입이 ESGMKG 클래스가 아닌 엔티티를 버린다(환각된 "Tagline" 거절). *2단계(규칙 기반 스키마 검사)*는 `(srcType, relation, dstType)`이 허용 ESGMKG 간선일 때만 관계를 채택한다 — 그래서 `CalculationModel`은 결코 `appliesToIndustry`를 가질 수 없다.

## 3. 구축 과정 (단계별)
1. **문서 읽기** — `esg_document.json`(`framework`, `page`·`heading`·`text`를 갖는 순서 있는 `segments`).
2. **구조 인지 분할** — 세그먼트를 순서대로 처리하며 `framework → category → metric` 컨텍스트와 페이지 출처를 추적.
3. **온톨로지 제약 추출** — 헤딩 접두사로 ESGMKG 타입 제안 + 결정론적 id 생성; 본문의 `computed by … model` → `CalculationModel`, `applies to … industry` → `Industry`.
4. **1단계 — 의미 타입 검증** — 제안 타입이 ESGMKG 스키마에 없는 엔티티 거절.
5. **2단계 — 규칙 기반 스키마 검사** — 허용 ESGMKG 간선이고 양 끝점이 1단계를 통과한 관계만 채택.
6. **출력** — `ontology.ttl`(OWL 클래스 + 객체 속성 + 타입화·라벨된 개체), `ontology.json`(Cytoscape; 인스턴스 노드에 결정론적 id + `provenance`), `steps.json`(세그먼트당 스냅샷, UI 재생용).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `esg_document.json` | `{"framework":"SASB", "segments":[{"page","heading","text"}, ...]}` |
| 출력 | `ontology.ttl` | OWL: ESGMKG `owl:Class`, `owl:ObjectProperty`, `rdfs:label`을 갖는 타입화 개체 |
| 출력 | `ontology.json` | 그래프; 인스턴스 노드에 `cls`, 결정론적 `id`, 페이지 `provenance` |
| 출력 | `steps.json` | 세그먼트별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 결정론적 헤딩 접두사 → 타입 제안; 결정론적 id 생성 + 규칙 기반 검증 — 안정적 골든 파일, 키 불필요.
- `gemini`/`anthropic`/`hf_local`: LLM이 세그먼트별 엔티티 타입을 제안; id 생성과 두 검증 단계는 결정론으로 유지되어 그래프 형태가 안정적. 키가 없으면 자동 MOCK 폴백.

## 6. 사용해 보기
1. `samples/esg_document.json`에서 카테고리 아래 `Metric:` 세그먼트를 추가하고 `hasMetric` 간선과 `MET:` id가 생기는지 본다.
2. ESGMKG가 아닌 헤딩 접두사(예: `Tagline:`)를 가진 세그먼트를 넣어 **1단계**가 환각 엔티티를 거절하는지 본다.
3. `Calculation Model:` 세그먼트에 `applies to the … industry`를 넣어 **2단계**가 불법 `appliesToIndustry` 간선을 거절하는지(같은 문구가 `Metric:` 세그먼트에서는 채택됨) 본다.
4. 실행: `python pipeline.py samples runs/out --backend mock` (또는 사이트의 **Run** 버튼). manifest의 `rejected_entities` / `rejected_relations`가 검증 감사 로그다.
