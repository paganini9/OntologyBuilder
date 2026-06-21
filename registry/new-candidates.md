# 신규 방법 catch-up — 2026-06-21 (Cowork 일일 자동 실행)

큐(next_easiest) 비어 있음 → 신규 탐색 + 검증 후, MOCK 자동구현 정책에 따라 2개 자동 구현·게시. **git push는 하지 않음**(로컬 커밋만, 사용자가 수동 push). Windows 토스트 알림 없음.

## 이번에 자동 구현·게시한 방법 (2)
| id | 방법 | arXiv | 차별점 | 난이도 |
|----|------|-------|--------|:---:|
| anchor-cti | ANCHOR: 스키마-무관 CTI KG (Hybrid Ontology Discovery + SHACL) | 2606.01208 (2026-05-31, U Penn) | 스키마 트리 검색-내비게이트 + SHACL 형식 검증, UCO/STIX/MALOnt를 동일 코드로 처리 | 4 |
| usd2kg | USD2KG: USD 장면 → KG 제로샷 LLM 온톨로지 그라운딩 | 2606.09134 (2026-06-08, TU Berlin/Fraunhofer FOKUS, ICRA 2026 J-WOSMARS) | 3 전략(이름/계층/CoT) 순차 적용 + 명명 체제(semantic/abbreviated/opaque) 전환으로 ablation 가시화 | 4 |

- 두 방법 모두 MOCK 백엔드로 키 없이 결정론적으로 동작, GPU/파인튜닝 불필요, 논문 요지 확보(WebSearch + arXiv abstract/HTML 본문 검증).
- 총 방법 수: 24 → **26** (전부 published).

## 검증
- 전체 pytest **204 통과**(신규 각 7개 테스트 포함: 골든 픽스처·결정론·OWL 유효성·차별 기능·schema/regime 전환 검증).
- 사이트 26개 KO/EN 빌드. Overview 26행(양언어).
- UI 렌더 게이트: 이 환경에 Playwright/Chromium 미설치 → **HTTP 렌더 검증으로 대체**(실서버 backend.app 기동 → /ko/·/en/ 정적 200, index에 신규 2건 노출, /api/methods/<id>/run 시 nodes/edges/steps/TTL 모두 비어있지 않음, KO/EN 문서 + 샘플 입력 정상 응답).

## 탐색했으나 미구현 (이미 등록/중복 또는 후순위)
- 2604.20795 = 기존 후보 `llm-external-onto-memory` (중복, 스킵).
- 2604.23090 (Multi-Agent Ontology Generation) = 이미 구현된 `multiagent-ontogen` (중복, 스킵).
- 2602.01276 (LLM-Driven Ontology Construction for Enterprise KG / OntoEKG) = 이미 구현된 `ontoekg` (중복, 스킵).
- 후순위 MOCK 가능 후보(다음 실행 대상): wikontic, autopkg, llm-external-onto-memory(SHACL로 다소 무거움).
- 고난도/보류(승인 대기, GPU·RL 등): agentic-kgr, agrag, ontokg-routing, lec-kg, compcq, ark-sail, hgnet.

## 자동탐색 시 제외(이미 구현, 26개)
cqbycq, code-de-kg, ontogenia, peshevski-product-kg, agentigraph, are-llms-effective-kgc, ontology-grounded-wikidata, karma, odke-plus, itext2kg, se-standards-zeroshot, gptkb, autoschemakg, elenchus, hf-local-demo, sac-kg, multiagent-ontogen, onto-kg-completion, ollm, ontoekg, raga, dial-kg, trace-kg, ontokb-iterative, anchor-cti, usd2kg.
