# OLLM — End-to-End 온톨로지 학습 (분류 체계 backbone)

> 출처: Lo, Jiang, Li, Jamnik, *End-to-End Ontology Learning with Large Language Models* (**OLLM**), arXiv:2410.23584. 코드: https://github.com/andylolu2/ollm

## 1. 한 줄 요약
평면적인 (주어, 관계, 목적어) 트리플을 캐는 대신, 텍스트에서 온톨로지의 **분류 체계 backbone** — 즉 개념들의 `rdfs:subClassOf`(is-a) 계층 — 을 **end-to-end** 로 학습한다.

## 2. 핵심 개념
- **Taxonomy / backbone**: 온톨로지의 뼈대는 is-a 트리다(예: `ElectricMotor ⊑ Motor ⊑ Component`). OLLM은 관계 추출의 부산물이 아니라 이 backbone 자체를 직접 목표로 삼는다.
- **End-to-end**: 원논문은 LLM을 *파인튜닝* 하여 계층을 한 번에 생성하게 한다(리프 노드 과적합을 막는 정규화 포함). 모델이 국소 간선이 아니라 구조 자체를 학습한다 — 이 점이 트리플/관계 추출 방법(CQbyCQ, "Are LLMs Effective KGC")과 구별되는 지점.
- **subClassOf 우선**: 모든 개념은 `owl:Class` 가 되고, `rdfs:subClassOf` 로 하나의 루트 트리에 연결된다.

## 3. 구축 프로세스 (단계별)
1. **텍스트 읽기** — `text.txt` 의 자유 텍스트를 문장 단위로 분리.
2. **개념 추출 (문장별)** — LLM(또는 MOCK 휴리스틱)이 핵심 개념을 PascalCase 클래스 이름으로 뽑는다. backbone에는 *개념 집합* 만 필요하므로 관계 종류는 쓰지 않는다. 문장마다 스냅샷: `cq = "(concepts) <문장>"`.
3. **분류 체계 유도** — 누적된 개념 위에 `subClassOf` backbone을 결정론적으로 구축:
   - **복합어 꼬리 규칙(compound-tail)**: 이름이 다른 알려진 개념으로 끝나는 개념은 그 개념의 자식이 된다 — `ElectricMotor` ⊑ `Motor`, `CoolantPump` ⊑ `Pump`, `TemperatureSensor` ⊑ `Sensor` (가장 길고 구체적인 일치 부모에 연결).
   - **루트 연결**: 부모를 못 얻은 나머지 상위 개념은 합성 루트 `Entity` 에 연결 → 하나의 연결된 분류 트리.
   스냅샷 1개: `cq = "(taxonomy) induce hierarchy"`.
4. **산출** — `ontology.ttl`(개념=`owl:Class`, 계층=`rdfs:subClassOf`), `ontology.json`(분류 그래프), `steps.json`(단계별 스냅샷).

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `text.txt` | 자유 텍스트(`.` `!` `?` 로 문장 분리) |
| 출력 | `ontology.ttl` | OWL: `owl:Class` + `rdfs:subClassOf` (Turtle) |
| 출력 | `ontology.json` | 분류 그래프 (노드=클래스, 간선=subClassOf 자식→부모) |
| 출력 | `steps.json` | 단계별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(테스트 golden 고정). 대문자 명사를 개념으로 추출하고, 복합어 꼬리 + 루트 규칙으로 subClassOf backbone을 유도.
- `gemini`/`anthropic`: env에 키가 있으면 실제 LLM이 더 풍부한 개념을 뽑는다. 분류 체계 유도는 동일(결정론)하여 backbone은 안정적. 키 없으면 자동으로 MOCK 폴백.
- 참고: 공개된 OLLM은 계층 생성을 위해 추가로 모델을 *파인튜닝* 한다. 본 구현은 **end-to-end 분류 목표** 는 유지하되, 키 없이 재현 가능하도록 결정론적 유도를 사용한다.

## 6. 직접 해보기
1. `samples/text.txt` 를 수정(예: `Motor` 와 `ElectricMotor` 처럼 기본 개념 + 복합어를 함께 넣어야 실제 subClassOf 간선이 생긴다).
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`) 실행.
3. 단계 슬라이더로 개념이 나타난 뒤 is-a 계층으로 정리되는 과정을 확인.
