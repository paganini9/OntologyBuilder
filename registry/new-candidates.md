# 신규 방법 후보 — 일일 탐색 리포트

> 갱신: 2026-06-26 (cowork daily-check). 이 파일은 **이번 실행분만** 담으며 매 실행 덮어쓴다. 누적 이력은 `daily-run.log` 참조.

## 이번 실행 요약
- 큐(`next_easiest`): 비어 있음(실행 전 32개 전부 published). 직전 실행(2026-06-24) 이후 새로 발표된 '구축' 논문은 이미 등록/중복 → 검증된 **미등록 on-core MOCK 방법 2건을 catch-up 자동구현·게시**.
- 자동구현·게시(MOCK, 키 없이 동작, GPU/파인튜닝 불필요, 난이도<8): **relrae**, **medkgent**.
- 승인 대기(자동구현 제외): **vspo** (LoRA 파인튜닝+GPU 필요).

## ✅ 자동구현·게시 (2건)
### 1. relrae — RELRaE (arXiv:2507.03829, Liverpool/Unilever)
- *LLM-Based Relationship Extraction, Labelling, Refinement, and Evaluation.*
- 실험실 자동화 XML 스키마를 온톨로지 스키마로 보강: **추출(구조적 암시관계) → 라벨링 → 정제(정규화·중복제거) → LLM 심판 평가**. 4단계 프롬프트 기반, 파인튜닝/GPU 불필요.
- MOCK: 라벨 맵 + 투명한 심판 점수 휴리스틱(결정론). 난이도 4.
- 검증: 자체 7테스트 + 전체 스위트 통과, 사이트 KO/EN 렌더·실행(mock) 정상(nodes 6/edges 6/steps 12/ttl).

### 2. medkgent — MedKGent (arXiv:2508.12393, MBZUAI 등)
- *A LLM Agent Framework for Constructing Temporally Evolving Medical Knowledge Graph.*
- 두 에이전트: **Extractor**(트리플+샘플링 기반 신뢰도+저신뢰 필터) + **Constructor**(일자별 통합, noisy-OR 강화, 극성 충돌 해소/supersede). 기성 프롬프트 LLM, 파인튜닝/GPU 불필요.
- MOCK: 관계 동사 맵 + 단서 기반 신뢰도(결정론). 난이도 5.
- 검증: 자체 7테스트(강화·충돌해소·필터 포함) + 전체 스위트 통과, 사이트 KO/EN 렌더·실행(mock) 정상(nodes 8/edges 4/steps 9/ttl).

## ⏳ 승인 대기 (자동구현 제외, `/impl-approve <id>` 후 `/impl-next`)
- **vspo** — VSPO: Validating Semantic Pitfalls in Ontology via LLM-Based CQ Generation (arXiv:2511.07991, Yonsei). 핵심 기법이 **LLaMA-3.1-8B-Instruct를 LoRA로 파인튜닝(2×RTX 3090)** 해 의미적 함정 검증 CQ를 생성 → 충실 재현에 GPU+파인튜닝 필수, 난이도 10. 데이터셋 구성(불일치 주입+템플릿 CQ)만은 MOCK 가능하나 헤드라인 기법은 자동구현 정책 제외.

## 기존 백로그 (변동 없음)
- GPU/RL 보류: agents-k1, agentic-kgr, ark-sail, hgnet, lec-kg, ontokg-routing, sac-kg(게시됨).
- off-core(구축 파이프라인 아님): agrag, compcq, idea2-cq, industrial-asset-kg, autopkg(멀티모달), llms-graphs-survey(서베이).

## 탐색 중 dedup 스킵(이미 등록/중복)
- 2604.20795(llm-external-onto-memory), 2602.01276(ontoekg), 2412.20942(ontology-grounded-wikidata), 2510.22590(atom-tkg), 2508.19428(llms4ol-2025), 2604.16258(CQ 특성 분석, 기존), 2510.20345·2606.11560(서베이/포지션, off-core).
