# SAC-KG — Generator → Verifier → Pruner 다단계(재귀) 적용

> 출처: Chen et al., *SAC-KG: Exploiting Large Language Models as Skilled Automatic Constructors for Domain Knowledge Graph*, ACL 2024.

## 1. 한 줄 요약
**시드 엔티티**에서 시작해 **Generator → Verifier → Pruner** 3단계 루프를 **레벨 단위로 반복(재귀)** 적용하여 도메인 지식 그래프를 원하는 깊이까지 키운다.

## 2. 핵심 아이디어
- **Generator**: LLM이 현재 프런티어의 각 엔티티를 확장하는 후보 트리플 `(관계, 자식 엔티티)`를 도메인 코퍼스에 기반해 제안한다.
- **Verifier**: 각 후보를 검증(관계/엔티티 타당성, 근거)해 신뢰할 수 있는 것만 남기고 confidence를 부여한다. 환각(hallucination)은 버린다.
- **Pruner**: KG의 *구조*를 제어한다 — 분기를 제한하고 중복/순환(cycle) 엣지를 제거해 그래프를 간결한 DAG로 유지한다.
- **다단계(재귀)**: 한 레벨에서 살아남은 자식들이 다음 레벨의 프런티어가 되고, 루프가 여러 레벨 반복된다.

## 3. 구축 과정 (단계별)
1. **시드 읽기** — `seed_entities.txt`에 한 줄당 시드 엔티티 하나(레벨 0 프런티어).
2. **각 레벨 L = 1..N에 대해:**
   - **L generate** — Generator가 프런티어 엔티티마다 후보 `(부모, 관계, 자식)` 트리플을 제안.
   - **L verify** — Verifier가 관계가 허용 어휘에 있고 자식이 타당한 엔티티인 후보만 남기고 나머지는 제거.
   - **L prune** — Pruner가 부모당 최대 **TOP_K**개 자식만 유지(안정 순서)하고 중복·순환 유발 엣지를 제거. 살아남은 것을 KG에 기록.
   - 살아남은 자식들이 다음 레벨 프런티어가 된다.
3. **산출** — `(레벨, 스테이지)`마다 스냅샷을 기록(UI가 루프를 재생)하고 `ontology.ttl`, `ontology.json`, `steps.json`을 쓴다.

## 4. 입력 / 출력
| 종류 | 파일 | 비고 |
|------|------|------|
| 입력 | `seed_entities.txt` | 시드 엔티티(한 줄당 하나, `#` 주석/빈 줄 무시) |
| 출력 | `ontology.ttl` | KG의 OWL/Turtle: 엔티티 `owl:Class`, 관계 `owl:ObjectProperty`(+domain/range) |
| 출력 | `ontology.json` | Cytoscape nodes/edges (시각화용) |
| 출력 | `steps.json` | `(레벨, 스테이지)`별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드 & MOCK 단순화
- **실제 방법에 필요한 것:** 원본 SAC-KG의 **Pruner**는 **GPU에서 동작하는 fine-tuned T5 + LoRA** 기반의 generation-relation 분류기이며, Generator/Verifier는 도메인 코퍼스를 활용하는 대형 LLM을 쓴다. 재현하려면 GPU + 파인튜닝 + API/HF 모델이 필요하다.
- **이 구현이 하는 것:** **결정론적 MOCK 단순화**다. **GPU·파인튜닝·API 키 없이** 동작한다. Generator는 고정 도메인 사전, Verifier는 규칙 검사(허용 관계 + 타당 엔티티), Pruner는 결정론적 대체물(top-K 분기 제한 + 중복/순환 제거)이다. 이는 **Generator → Verifier → Pruner 다단계 루프**를 충실히 재현하며, 테스트·시각화를 위한 안정적인 golden 산출물을 만든다.
- **향후 옵션:** T5-LoRA pruner를 쓰는 실제 `hf-local`/GPU 실행으로 MOCK 대체물을 교체할 수 있다. 여기서는 **하지 않는다**.

## 6. 직접 해보기
1. `samples/seed_entities.txt`를 수정(예: 사전에 있는 시드 `Engine` 추가).
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 각 레벨의 **generate → verify → prune** 스테이지가 후보를 추가/제거하는 과정을 본다.
