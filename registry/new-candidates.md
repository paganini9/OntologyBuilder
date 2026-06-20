# 신규 방법 catch-up — 2026-06-20 (Cowork 일일 자동 실행)

일일 자동 작업(Cowork)으로 실행. 큐(next_easiest) 비어 있음 → 신규 탐색 + 검증 후, MOCK 자동구현 정책에 따라 2개 자동 구현·게시. **git push는 하지 않음**(로컬 커밋만, 사용자가 수동 push). Windows 토스트 알림 없음.

## 이번에 자동 구현·게시한 방법 (2)
| id | 방법 | arXiv | 차별점 | 난이도 |
|----|------|-------|--------|:---:|
| trace-kg | TRACE-KG: 텍스트 기반 스키마 + 관계 한정자 + 출처 추적 | 2604.03496 (2026, ASU) | 사전 온톨로지 없이 텍스트에서 스키마 유도, 조건 한정자(when/if/...), 모든 엣지 원문 추적 | 3 |
| ontokb-iterative | 반복형 LLM 온톨로지 KB (초안→정제) | 2601.10436 (2026) | 생성→검토→정제 사이클; 초안=뼈대, 정제=계층+데이터 속성 보강(감사 가능) | 4 |

- 두 방법 모두 MOCK 백엔드로 키 없이 결정론적으로 동작, GPU/파인튜닝 불필요, 논문 요지 확보(WebSearch+arXiv 검증).
- 총 방법 수: 22 → **24** (전부 published).

## 검증
- 전체 pytest **통과**(신규 각 6개 테스트 포함, 골든 픽스처·결정론·OWL 유효성·차별 기능 검증).
- 사이트 24개 KO/EN 빌드. Overview 24행(양언어).
- UI 렌더 게이트: 이 환경에 Playwright/Chromium 미설치 → **HTTP 렌더 검증으로 대체**(실서버 backend.app 기동 → /ko/·/en/ 정적 200, overview 24행, 신규 2개 method 실행 시 그래프(노드/엣지)·steps·TTL·KO/EN 문서·샘플 모두 정상 렌더 확인). verify_ui.py는 구 방법만 하드코딩하므로 신규 방법엔 본 HTTP 검증이 더 직접적.

## 탐색했으나 미구현 (이미 등록/중복 또는 후순위)
- OntoKG (2604.02618) = 기존 후보 `ontokg-routing`, LLM-as-external-onto-memory (2604.20795) = 기존 후보 `llm-external-onto-memory` — 중복, 스킵.
- 후순위 MOCK 가능 후보(다음 실행 대상): wikontic, autopkg(제품KG 중복 소지), llm-external-onto-memory(SHACL로 다소 무거움).
- 고난도/보류(승인 대기, GPU·RL 등): agentic-kgr, agrag, ontokg-routing, lec-kg, compcq, ark-sail, hgnet.

## 자동탐색 시 제외(이미 구현, 24개)
cqbycq, code-de-kg, ontogenia, peshevski-product-kg, agentigraph, are-llms-effective-kgc, ontology-grounded-wikidata, karma, odke-plus, itext2kg, se-standards-zeroshot, gptkb, autoschemakg, elenchus, hf-local-demo, sac-kg, multiagent-ontogen, onto-kg-completion, ollm, ontoekg, raga, dial-kg, trace-kg, ontokb-iterative.
