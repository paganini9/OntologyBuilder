# 신규 방법 catch-up — 2026-06-19 (수동 일일 업데이트)

일일 자동 작업이 6/15~6/19 동안 작업 디렉터리 버그로 실패해(이후 수정), 오늘 수동으로 catch-up 업데이트를 실행했다. exa 탐색 → WebFetch 실재 검증 → MOCK+실모델 경로 구현 → 테스트·UI 검증 → push.

## 이번에 자동 구현·게시한 방법 (3)
| id | 방법 | arXiv | 차별점 | 실모델(GPU) |
|----|------|-------|--------|:---:|
| multiagent-ontogen | 4역할 멀티에이전트(Domain Expert/Manager/Coder/QA) 온톨로지 생성 | 2604.23090 (2026) | 아티팩트 기반 4역할 계획기반 + QA 가지치기 | ✅ 10n/10e |
| onto-kg-completion | 온톨로지 제약 기반 KG 완성 | 2507.20643 (2025) | 부분 KG 입력→누락 링크 예측(완성 패러다임) | ✅ 5n/9e |
| ollm | OLLM 분류체계(subClassOf) backbone end-to-end | 2410.23584 (2024, 코드공개) | 관계 아닌 is-a 계층 학습 | ✅ 18n/17e |

총 방법 수: 16 → **19** (전부 published, MOCK 기본 + hf_local 실모델 경로).

## 검증
- 전체 pytest **152 passed**.
- 3개 모두 RTX 3080 Ti(Qwen2.5-1.5B) 실모델에서 비어있지 않은 온톨로지 생성.
- 사이트 19개 빌드(KO/EN), Overview 19행, 그래프 렌더 확인(Playwright).

## 제외/대기 후보 (탐색됐으나 미구현)
- 고난도/중복 또는 미검증: OntoEKG(2602.01276), RAGA(2605.17072), Agentic-KGR(2510.09156), DIAL-KG(2603.20059), GraphAgents(2602.07491), AGRAG(2511.05549), Ontology-Constrained Neural Reasoning(2604.00555), CAR(2604.09608), CQ-generation(2604.16258) 등. 다음 일일 실행에서 재검증 후 순차 구현 가능.

## 자동탐색 시 제외(이미 구현, 19개)
cqbycq, code-de-kg, ontogenia, peshevski-product-kg, agentigraph, are-llms-effective-kgc, ontology-grounded-wikidata, karma, odke-plus, itext2kg, se-standards-zeroshot, gptkb, autoschemakg, elenchus, hf-local-demo, sac-kg, multiagent-ontogen, onto-kg-completion, ollm.
