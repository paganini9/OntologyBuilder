# Wikontic — Wikidata 정렬·온톨로지 인지 지식그래프 구축

> 출처: *Wikontic: Constructing Wikidata-Aligned, Ontology-Aware Knowledge Graphs with Large Language Models*, arXiv:2512.00590.

## 1. 한 줄 요약
열린 도메인 텍스트에서, **한정자(qualifier)를 가진 후보 트리플을 추출**하고, 표면형 멘션을 **정규화하여 하나의 표준 Wikidata 항목(QID)으로 병합**하며, **Wikidata 타입·관계 제약**을 강제해 온톨로지에 부합하는 진술만 남기는 다단계 파이프라인이다. 결과 KG는 작고 일관되며 잘 연결된다.

## 2. 핵심 아이디어
- **Wikidata 정렬.** 모든 항목은 표준 Wikidata 항목(QID)으로, 모든 관계는 Wikidata 속성(PID)으로 표현된다 — 외부 지식과 즉시 정합.
- **한정자가 있는 후보 트리플.** 관계 어휘집으로 각 문장에서 `(주어, 속성, 목적어)`를 뽑고, 끝의 `in <연도>` / `since <연도>` 절을 **Wikidata 한정자**(시점 P585 / 시작시점 P580)로 부착한다.
- **엔티티 정규화(중복 제거).** 표면형 멘션("Apple", "Apple Inc.")을 별칭 표를 통해 **하나의 표준 항목**(Q312, 타입 포함)으로 정규화한다 — 중복 멘션이 한 노드로 합쳐진다.
- **Wikidata 타입·관계 제약.** 모든 속성은 주어 타입·값 타입 제약을 가진다(예: `foundedBy`/P112 는 주어가 Organization, 값이 Person). 정규화된 양 끝점이 제약을 어기는 진술은 거절된다 — Wikidata 속성 제약을 그대로 모사.

## 3. 구축 과정 (단계별)
1. **문장 읽기** — `passages.txt`(한 줄당 한 문장; 빈 줄·`#` 주석 무시).
2. **후보 트리플 추출** — 관계 어휘집으로 `(주어, 속성, 목적어)` 추출, 끝의 시간 절은 한정자로 분리.
3. **엔티티 정규화** — 표면형을 별칭 표로 표준 Wikidata 항목(QID + 타입)에 매핑; 같은 항목으로 풀리는 멘션은 한 노드로 병합.
4. **제약 강제** — `(주어타입, 속성, 값타입)`이 허용될 때만 진술 채택; 위반은 거절(감사 로그).
5. **출력** — `ontology.ttl`(타입화된 항목 + 객체 속성 + `rdfs:seeAlso`로 Wikidata 링크), `ontology.json`(Cytoscape; 항목 노드는 QID + 클래스, 관계 간선은 PID + 한정자), `steps.json`(문장당 스냅샷).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `passages.txt` | 한 줄당 한 문장 |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty`, 타입화 항목(`rdfs:label` + Wikidata `rdfs:seeAlso`) |
| 출력 | `ontology.json` | 그래프; 항목 노드에 `qid`·`cls`, 관계 간선에 `pid`·`qualifiers` |
| 출력 | `steps.json` | 문장별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 결정론적 문장 파싱 → 후보 트리플 + 한정자; 정규화·제약은 규칙 기반 — 안정적 골든 파일, 키 불필요.
- `gemini`/`anthropic`/`hf_local`: LLM이 문장별 트리플을 추출; 정규화·제약 강제는 결정론으로 유지. 키가 없으면 자동 MOCK 폴백.

## 6. 사용해 보기
1. `samples/passages.txt`에서 `Apple`과 `Apple Inc.`가 **하나의 노드(Q312)**로 합쳐지는 것을 확인한다(`merged` 카운트).
2. 제약을 어기는 문장(예: 도시를 주어로 `was founded by`)을 추가해 진술이 **거절**되는지 본다(`manifest.rejected`).
3. `in <연도>` / `since <연도>` 절을 붙여 간선에 **한정자**(P585/P580)가 실리는지 본다.
4. 실행: `python pipeline.py samples runs/out --backend mock` (또는 사이트의 **Run** 버튼).
