# OntoEKG — 기업용 지식 그래프를 위한 2단계 온톨로지 구축

> 출처: Oyewale & Soru, *LLM-Driven Ontology Construction for Enterprise Knowledge Graphs* (**OntoEKG**), arXiv:2602.01276 (2026).

## 1. 한 줄 요약
기업용 OWL 온톨로지를 **두 단계**로 구축한다: 텍스트에서 핵심 **클래스** 와 **객체 속성** 을 함께 뽑는 **EXTRACTION(추출)** 모듈과, 그 클래스들을 `rdfs:subClassOf` 계층으로 논리적으로 구조화한 뒤 RDF로 직렬화하는 **ENTAILMENT(함의)** 모듈.

## 2. 핵심 개념
- **두 모듈, 하나의 파이프라인**: Phase A(추출)는 기업 텍스트를 읽어 개념 집합과 그것들을 잇는 관계를 만들고, Phase B(함의)는 개념 집합 위에서 is-a 계층을 유도해 전체를 RDF/OWL로 직렬화한다.
- **클래스 AND 객체 속성 둘 다**: 분류 체계 backbone만 목표로 하는 OLLM과의 핵심 차이. OntoEKG는 관계 간선(도메인/레인지를 가진 객체 속성)을 유지하면서 **그 위에** 함의 계층을 추가하므로, 최종 그래프에는 두 종류의 간선이 존재한다.
- **기업(enterprise) 초점**: 제품 라인, 설비, 조직 구조 등 — 엔티티 간 관계와 깔끔한 클래스 계층이 모두 중요한 기업용 지식 그래프를 겨냥한다.
- **구조화로서의 함의(entailment)**: 계층은 문장별로 추출되는 게 아니라, 누적된 클래스 집합 위에서 결정론적으로 *함의* 되어 하나의 연결된 재현 가능한 backbone을 만든다.

## 3. 구축 프로세스 (단계별)
1. **텍스트 읽기** — `text.txt` 의 기업 자유 텍스트를 문장 단위로 분리.
2. **Phase A — EXTRACTION (문장별)** — LLM(또는 MOCK 휴리스틱)이 핵심 **클래스**(PascalCase 개념)와 그 사이의 **객체 속성**(관계 `{name, domain, range}`)을 뽑는다. 문장마다 스냅샷: `cq = "(extract) <문장>"`. 실제 백엔드에서는 공유 트리플 추출기가 각 `(subject, relation, object)` 트리플을 두 클래스 + 하나의 객체 속성으로 매핑한다.
3. **Phase B — ENTAILMENT** — 누적된 클래스 위에 `subClassOf` 계층을 결정론적으로 구조화:
   - **복합어 꼬리 규칙(compound-tail)**: 이름이 다른 알려진 클래스로 끝나는 클래스는 그 하위 클래스로 함의된다 — `ElectricMotor` ⊑ `Motor`, `CoolantPump` ⊑ `Pump` (가장 길고 구체적인 일치 부모에 연결).
   - **루트 연결**: 부모를 못 얻은 나머지 상위 클래스는 합성 루트 `Entity` 에 연결 → 하나의 연결된 계층.
   스냅샷 1개: `cq = "(entail) hierarchy"`.
4. **산출** — `ontology.ttl`(클래스=`owl:Class`, 관계=`owl:ObjectProperty`+도메인/레인지, 계층=`rdfs:subClassOf`), `ontology.json`(객체 속성 간선 + is-a 간선을 합친 그래프), `steps.json`(단계별 스냅샷).

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `text.txt` | 기업 자유 텍스트(`.` `!` `?` 로 문장 분리) |
| 출력 | `ontology.ttl` | OWL: `owl:Class` + `owl:ObjectProperty`(도메인/레인지) + `rdfs:subClassOf` (Turtle) |
| 출력 | `ontology.json` | 그래프: 노드=클래스, 간선=객체 속성 AND subClassOf(자식→부모) |
| 출력 | `steps.json` | 단계별 스냅샷 — 추출 단계들 뒤에 함의 단계 1개 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(golden 고정). 대문자 명사를 클래스로, 관계 동사를 객체 속성으로 추출하고, 복합어 꼬리 + 루트 규칙으로 subClassOf 계층을 함의한다.
- `gemini`/`anthropic` (`llm_dependency: api`): env에 키가 있으면 실제 LLM이 더 풍부한 트리플을 뽑는다(Phase A는 공유 `extract_triples` 헬퍼 사용). Phase B의 함의는 동일(결정론)하여 계층은 안정적. 키 없으면 자동 MOCK 폴백.

## 6. 직접 해보기
1. `samples/text.txt` 를 수정(관계 동사 AND 기본+복합 개념, 예: `Motor` 와 `ElectricMotor` 를 함께 넣어야 객체 속성과 subClassOf 간선이 모두 생긴다).
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`) 실행.
3. 단계 슬라이더로 클래스와 객체 속성이 나타난 뒤(Phase A) is-a 계층으로 정리되는 과정을 확인(Phase B).
