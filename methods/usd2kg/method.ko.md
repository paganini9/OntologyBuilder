# USD2KG — USD 장면을 위한 제로샷 LLM 온톨로지 그라운딩

> 출처: *From USD Scenes to Knowledge Graphs: Zero-Shot Ontology Grounding with LLMs*, arXiv:2606.09134, Shuai 외, IEEE ICRA 2026 J-WOSMARS 워크숍. 코드: <https://github.com/JTShuai/USD_2_KG>.

## 1. 한 줄 요약
USD prim → OWL 클래스 매핑을 위해 수작업 사전 대신, 각 prim에 대해 (A) 이름 단독, (B) 장면 그래프 계층(부모 경로+형제 이름) 보강, (C) 바운딩 박스 기하에 대한 사고연쇄(CoT)를 **순차 적용**해 가장 구체적인 클래스를 부여하는 **제로샷 LLM 그라운딩** 파이프라인.

## 2. 핵심 아이디어
- **USD prim → OWL 클래스가 병목**: 3D 장면에서 지식그래프를 만들려면 자산별 사전이 필요했다. 논문은 LLM이 의미 있는 이름에선 90–96%, 완전 익명 이름에서도 17–48% 정확도로 그라운딩할 수 있음을 보인다.
- **세 가지 프롬프트 전략, 단일 파이프라인**: 각 prim에 입력 풍부도가 다른 세 전략을 순차 시도한다 — (A) 이름만, (B) 이름 + 부모 경로 + 형제 이름, (C) (B) + 기하 추론. 가장 먼저 통과한 전략이 클래스를 확정하고 선택 사실이 기록된다(ablation).
- **명명 체제(naming regime)**: 같은 장면을 *semantic / abbreviated / opaque*로 재실행할 수 있다. 논문은 이름이 망가질수록 계층(부모 경로·형제 이름)이 핵심이라고 보고하는데, 이 파이프라인의 전략 분포 변화로 그 결과가 재현된다.
- **TBox 선형화**: 온톨로지는 클래스명+설명을 알파벳순 평면 리스트로 LLM에 제시한다(논문 프롬프트 형식; 위치 편향은 인지하고 있음).

## 3. 구축 과정 (단계별)
1. **장면 읽기** — `usd_scene.json`(`naming_regime`, `name`·`parent_path`·`bbox=[w,h,d]`·선택적 `mass`를 갖는 prim 목록).
2. **명명 체제 적용** — `semantic`은 그대로, `abbreviated`는 모음 제거+단어별 단축, `opaque`는 `obj_NNN`으로 치환.
3. **전략 A — 이름 단독** — LLM(또는 MOCK 휴리스틱)이 prim 이름을 선형화된 TBox(별칭 테이블+클래스명 부분일치, 최장 우선)에 매칭.
4. **전략 B — 컨텍스트 보강** — A가 비면 `parent_path`에서 가장 가까운 그룹을 읽어 슈퍼클래스를 부여(예: `Crockery_grp` → `Crockery`; 논문의 "superclass collapse" 동작).
5. **전략 C — 기하 추론** — B도 비면 바운딩 박스 부피 버킷으로 슈퍼클래스 결정(`DesignedFurniture` / `Appliance` / `PhysicalObject`).
6. **출력** — `ontology.ttl`(OWL 클래스+`rdfs:subClassOf` 계층+타입화 개체), `ontology.json`(Cytoscape; 인스턴스 노드에 `strategy`·`feature` 포함), `steps.json`(prim당 스냅샷, UI 재생용).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `usd_scene.json` | `{"ontology":..., "naming_regime":"semantic\|abbreviated\|opaque", "prims":[...]}` |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf`, 타입화 개체 |
| 출력 | `ontology.json` | 그래프; 인스턴스 노드에 `strategy`(A/B/C)·`feature`(name/hierarchy/geometry) |
| 출력 | `steps.json` | prim별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 결정론적 이름 시드 + 결정론적 계층/기하 폴백 — 키 없이 안정적 골든 파일.
- `gemini`/`anthropic`/`hf_local`: LLM은 전략 A 클래스만 제안하고 B·C는 결정론이라 그래프 형태는 안정. 키 없으면 자동 MOCK.

## 6. 사용해보기
1. `samples/usd_scene.json`을 편집 — 잘 명명된 prim(`Refrigerator_main`), 기괴한 이름(`obj_042`), `/Misc_grp` 아래의 "잡동사니"를 섞어 C 전략까지 흐르게 한다.
2. `naming_regime`을 `opaque`로 바꿔 전략 분포가 (B)로 이동하는 모습을 본다(논문 결과 재현).
3. 사이트의 **Run** 버튼을 누르거나 `python pipeline.py samples runs/out --backend mock`.
4. 슬라이더가 단계별 그라운딩을 보여주며, manifest의 `strategies` 블록이 ablation 요약이다.
