# CoDe-KG — 상호참조 해소 + 문장 분해로 트리플 추출

> 출처: Anuyah, Kaushik, Dwarampudi, Shiradkar, Durresi, Chakraborty, *Automated Knowledge Graph Construction using Large Language Models and Sentence Complexity Modelling* (CoDe-KG), EMNLP 2025 (arXiv:2509.17289). 코드: github.com/KaushikMahmud/CoDe-KG_EMNLP_2025.

## 1. 한 줄 요약
자유 텍스트를 **상호참조 해소 → 문장 분해 → 문장 복잡도별 프롬프트 선택 → 트리플 추출 → KG 병합** 순서로 처리해, 긴 문장·대명사가 많은 글에서도 (주어, 관계, 목적어) 트리플 기반 온톨로지를 안정적으로 뽑아낸다.

## 2. 핵심 개념
- **상호참조 해소(Coreference Resolution)**: "그것", "이 부품" 같은 참조 표현을 실제 엔티티 이름으로 치환한다. 원논문은 Mixtral + FICL 프롬프트로 단축 표현 → 완전 지시어 매핑(JSON)을 만들어 토큰을 교체한다. 이 단계가 희귀 관계 recall을 20%p 이상 끌어올린다.
- **문장 분해(Sentence Decomposition)**: 복잡한 문장을 더 단순한 절(clause) 단위로 쪼갠다. 추출기가 한 번에 하나의 사실만 다루게 해 정확도를 높인다.
- **복잡도별 프롬프트 선택**: 각 문장을 복잡도(단순/중문/복문/혼합문)로 분류하고, 복잡도에 맞는 프롬프트–모델 조합을 고른다(hybrid chain-of-thought + few-shot). 원논문은 fine-tuned BERT-Large 분류기를 쓰지만, 본 구현은 GPU·파인튜닝 없이 동작하도록 절·접속사 개수를 세는 결정론적 규칙 분류기로 대체한다.
- **트리플(Triple)**: (entity_1, relationship, entity_2). 이 트리플들이 온톨로지 그래프의 노드(엔티티/클래스)와 엣지(관계)가 된다.

## 3. 구축 프로세스 (단계별)
1. **텍스트 수집** — `text.txt` 한 파일에 자유 형식의 본문(문단). 빈 줄로 문단을 나눌 수 있다.
2. **상호참조 해소** — 본문 내 대명사·축약 참조를 가장 가까운 선행 엔티티로 치환한다. (LLM 백엔드 또는 MOCK 규칙)
3. **문장 분리·분해** — 치환된 본문을 문장으로 나누고, 복잡한 문장은 단순 절들로 분해한다.
4. **복잡도 분류 → 프롬프트 선택** — 각 (분해된) 문장을 단순/중문/복문/혼합문으로 분류하고, 그에 맞는 추출 프롬프트를 선택한다.
5. **트리플 추출** — 선택된 프롬프트로 각 문장에서 (entity_1, relationship, entity_2) 트리플을 추출한다.
6. **KG/온톨로지 병합** — 트리플을 누적 그래프에 합친다. 같은 엔티티는 하나의 노드로 통합(클래스화), 동일 트리플은 중복 제거. 문장 처리마다 스냅샷을 남겨 그래프가 자라는 과정을 보여준다.
7. **산출** — `ontology.ttl`(OWL/Turtle), `ontology.json`(Cytoscape 그래프), `steps.json`(단계별 스냅샷)을 쓴다.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `text.txt` | 자유 형식 본문(문단). 빈 줄로 문단 구분, 문장 단위 자동 분리 |
| 출력 | `ontology.ttl` | 트리플 기반 OWL 온톨로지 (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes(엔티티/클래스)/edges(관계) — 시각화용 |
| 출력 | `steps.json` | 문장(또는 단계)별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(테스트 golden 고정). 상호참조는 간단한 규칙(대명사 → 직전 대문자 명사구)으로, 트리플은 "주어(대문자 명사) – 관계 동사 – 목적어(대문자 명사)" 패턴으로 추출.
- `gemini`/`anthropic`(api): env에 키가 있으면 실제 LLM이 상호참조·분해·추출을 더 정교하게 수행. 키 없으면 자동 MOCK 폴백.
- 원논문은 단계별로 다른 모델(Mixtral, LLaMA-3.1-8B, LLaMA-3.3-70B)을 복잡도에 따라 라우팅한다. 본 구현은 단일 설정형 백엔드 하나로 통합해 복잡도 분기는 프롬프트 선택으로만 반영한다(파인튜닝·GPU 불필요).

## 6. 직접 해보기
1. `samples/text.txt` 의 본문을 자신의 문서(매뉴얼·설명 등)로 교체.
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`) 실행.
3. 문장이 처리될 때마다 트리플이 추가되며 그래프가 커지는 과정을 단계 슬라이더로 확인.
