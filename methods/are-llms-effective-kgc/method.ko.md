# 계층적 추출 (Are LLMs Effective KG Constructors?)

> 출처: *Are Large Language Models Effective Knowledge Graph Constructors?*, 2025 (arXiv:2510.11297).

## 1. 한 줄 요약
텍스트에서 **계층적·다단계(hierarchical, multi-level)** 로 지식을 뽑는다 — 먼저 엔티티(개념)를, 다음 그들 사이의 관계를, 마지막에 상위/하위 계층을 정리해 온톨로지를 만든다. 동시에 LLM의 KG 구축 한계를 체계적으로 평가하는 관점을 제공한다.

## 2. 핵심 개념
- **계층적 추출**: 한 번에 트리플을 뽑지 않고 **레벨별**로 나눈다 — (L1) 핵심 엔티티/개념, (L2) 엔티티 간 관계, (L3) 개념 계층(상위/하위, is-a).
- **다단계 정련**: 각 레벨이 이전 레벨의 산출을 입력으로 받아 점진적으로 구조를 키운다.
- **체계적 평가 관점**: 추출 결과의 커버리지·일관성을 단계별로 점검(원논문은 LLM KGC의 한계를 정량 평가).

## 3. 구축 프로세스 (단계별)
1. **텍스트 수집** — `text.txt` 자유 본문.
2. **L1 엔티티 추출** — 문장에서 핵심 개념(대문자 명사 등)을 클래스 후보로 추출.
3. **L2 관계 추출** — 추출된 엔티티 쌍 사이의 관계(객체 속성)를 추출.
4. **L3 계층 정리** — is-a/상위·하위 관계를 추론해 클래스 계층(subClassOf)을 만든다.
5. **병합·산출** — 레벨마다 스냅샷을 남겨 "엔티티→관계→계층" 순으로 구조가 서는 과정을 보여주고, `ontology.ttl`·`ontology.json`·`steps.json`을 쓴다.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `text.txt` | 자유 본문 |
| 출력 | `ontology.ttl` | 계층(subClassOf) 포함 OWL (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges |
| 출력 | `steps.json` | 레벨(L1·L2·L3)별 스냅샷 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작. L1은 대문자 명사 추출, L2는 관계동사 패턴, L3은 규칙 기반 is-a(예: 복합어의 머리명사로 상위 클래스 추론).
- `gemini`/`anthropic`(api): 키가 있으면 실제 LLM이 레벨별 추출을 수행. 키 없으면 자동 MOCK 폴백.

## 6. 직접 해보기
1. `samples/text.txt` 를 자신의 문서로 교체.
2. **Run**(또는 `python pipeline.py samples runs/out`) 실행.
3. 단계 슬라이더로 L1→L2→L3 순서로 그래프와 계층이 형성되는 과정을 확인.
