# RELRaE — XML 스키마 → 온톨로지 관계 (추출 · 라벨링 · 정제 · 평가)

> 출처: *RELRaE: LLM-Based Relationship Extraction, Labelling, Refinement, and Evaluation*, arXiv:2507.03829 (Hannah 외, University of Liverpool / Unilever Materials Innovation Factory).

## 1. 한 줄 요약
로봇 실험실은 대량의 **XML**을 만든다. 이 데이터를 지식그래프로 상호운용하려면 XML *스키마*를 **온톨로지 스키마**로 바꿔야 하는데, 요소 타입 사이의 관계는 XML 안에 **암시적으로만** 존재한다. RELRaE는 LLM을 네 단계로 써서 이 관계를 드러낸다: **추출 → 라벨링 → 정제 → 평가**.

## 2. 핵심 아이디어
- **관계는 구조에 암시돼 있다.** 부모/자식 요소 중첩은 *포함(containment)* 관계를, `Ref`로 끝나는 속성은 다른 요소 타입에 대한 *상호참조*를, 나머지 속성은 *데이터 속성*을 인코딩한다. 그 자체로는 온톨로지 라벨이 없다.
- **LLM 라벨링.** 추출된 각 구조적 관계를 모델에 넘겨 의미 있는 객체 속성 라벨을 제안받는다(예: `Measurement`–`Instrument` 사이의 `instrumentRef` → 일반적인 `ref`가 아니라 `measuredWith`).
- **정제(Refinement).** 모든 샘플·측정마다 반복되는 동일 `(도메인, 라벨, 레인지)` 구조를 하나의 온톨로지 관계로 합치고, 동의어 라벨을 정규화한다.
- **LLM 심판(LLM-as-a-judge).** 라벨링된 각 관계의 품질을 점수화해 낮은 점수는 기각하여, 최종 스키마에는 신뢰할 만한 관계만 남긴다. 대상 타입이 문서에 정의되지 않은 참조는 감점된다.

## 3. 구축 과정 (단계별)
1. **추출(Extract)** — `schema.xml`을 파싱해 트리를 순회. 부모→자식 요소 쌍마다 *nest* 관계, `…Ref` 속성마다 *ref* 관계(대상 타입은 속성명에서 유도, 예: `instrumentRef` → `Instrument`), 그 외 속성마다 데이터 속성을 만든다.
2. **라벨링(Label)** — LLM(또는 MOCK 휴리스틱)이 각 관계에 이름을 붙인다: 포함 → `has<Child>`, 참조 → 사용 동사(`measuredWith`, `consumes`, …).
3. **정제(Refine)** — 동의어 라벨을 정규화한 뒤 `(도메인, 라벨, 레인지)`로 중복 제거하여 반복 구조를 하나의 관계로 만든다.
4. **평가(Evaluate)** — LLM 심판이 각 관계에 `[0,1]` 점수를 매기고, 임계값 미만(또는 중복) 관계는 기각해 온톨로지에서 제외한다.

원시 관계마다 스냅샷을 남겨, 추출·라벨링·정제·심판 과정과 관계가 수락되며 스키마가 자라는 모습을 UI에서 재생할 수 있다.

## 4. 입력 / 출력
| 종류 | 파일 | 설명 |
|------|------|------|
| 입력 | `schema.xml` | 실험실 XML 1건; 중첩=포함, `…Ref` 속성=상호참조, 그 외 속성=데이터 속성 |
| 출력 | `ontology.ttl` | OWL: 요소 타입=`owl:Class`, 수락된 관계=`owl:ObjectProperty`(domain/range), 속성=`owl:DatatypeProperty`; 관계별 심판 점수는 `rdfs:comment` |
| 출력 | `ontology.json` | 그래프; 각 관계 엣지가 `label`, `kind`(nest/ref), `score`, `accepted`를 가짐 |
| 출력 | `steps.json` | 관계별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 결정론적·키 불필요(골든 파일 안정). 라벨 맵이 객체 속성명을, 투명한 휴리스틱이 심판 점수를 만들어 라벨링·평가가 재현 가능하다.
- `gemini` / `anthropic` / `hf_local`: 실제 모델이 각 관계를 라벨링·점수화하고, 구조 추출과 정제는 규칙 기반으로 유지해 스키마 형태가 안정적이다. 키가 없으면 자동으로 MOCK으로 폴백.
- 참고: 발표된 RELRaE는 실험실 자동화 XML에 대한 사람-개입 반자동 온톨로지 생성을 목표로 한다. 본 구현은 **추출 → 라벨링 → 정제 → 평가** 핵심을 유지하면서 키 없이 재현 가능하게 동작한다.

## 6. 사용해 보기
1. `samples/schema.xml`을 편집 — 요소를 중첩하고, 다른 요소 타입을 가리키는 `…Ref` 속성과 평범한 속성(데이터 속성)을 추가한다.
2. **Run**(또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 관계가 라벨링·병합·심판되는 과정을 보고, 엣지에 마우스를 올려 라벨·종류·심판 점수를 확인한다.
