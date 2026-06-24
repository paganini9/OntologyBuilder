# 신규 방법 — 2026-06-25 (Cowork 일일 자동 실행)

큐(next_easiest) 비어 있음(이번 실행 전 30개 전부 published). 직전 실행(2026-06-24) 이후 새로 **발표된** 온톨로지/지식그래프 '구축' 논문은 발견되지 않음(검색 결과 대부분 이미 등록된 라이브러리/후보거나 서베이·분석 논문). 기존 catch-up 정책에 따라, **검증된 on-core·MOCK 구현 가능·미등록** 방법 2건을 자동 구현·게시했다. 자동 구현 상한(2건) 도달. git push 안 함(로컬 커밋만, 사용자가 Windows에서 수동 push). Windows 토스트 알림 없음.

## 자동 구현·게시 (2) — MOCK 결정론, GPU/파인튜닝 불필요, 난이도<8
| id | 방법 | arXiv | 난이도 | 핵심/차별점 |
|----|------|-------|:---:|------|
| atom-tkg | ATOM: 이중시간(dual-time) 시간 지식그래프 | 2510.22590 (Lairgi 외, INSA Lyon) | 3 | 노트를 원자적 사실로 분해 → **관측(observed) vs 유효(valid) 이중시간** 태깅 → 병렬 병합 시 재관측이 유효 구간을 **확장**. 동적·시간 KG로 기존 30개와 차별. |
| llms4ol-2025 | LLMs4OL 2025: 이종 LLM 온톨로지 학습(용어→타입→분류체계) | 2508.19428 (Beliaeva·Rahmatullaev) | 2 | 3개 OL 서브태스크(A Text2Onto, B 검색 기반 용어 타이핑, C is-a 분류체계) 한 파이프라인. **미지 용어를 최근접 예시로 검색 타이핑**(임베딩 코사인의 키 없는 결정론 대체). 공개 코드. |

## 검증 (실재 확인 + 게이트)
- **atom-tkg** (2510.22590): arXiv PDF web_fetch로 초록 실재 확인 — "atomic facts", "dual-time modeling … when information is observed / when it is valid", "merged in parallel" 명시. 환각 아님.
- **llms4ol-2025** (2508.19428): arXiv PDF web_fetch로 전문 확인 — LLMs4OL 2025 Tasks A/B/C(term extraction, typing, taxonomy), 공개 코드(github.com/BelyaevaAlex/LLMs4OL-Challenge-Alexbek). 환각 아님.
- **테스트/UI 게이트**: 전체 pytest **248 통과**(신규 atom-tkg 6 + llms4ol-2025 6). 사이트 KO/EN 재빌드 **32개**(overview 32행). Playwright 미설치 → HTTP 렌더 검증으로 대체(실서버 uvicorn :8092 → `/ko`·`/en` 200, `/api/methods/<id>/run`(mock): atom-tkg nodes=5/edges=7/steps=5/ttl=1441, llms4ol-2025 nodes=15/edges=12/steps=12/ttl=1173, 모두 비어있지 않음). comparison.json 양언어 행 추가.

## 중복(dedup)으로 스킵
- **2509.17289 (CoDe-KG)** → 이미 `code-de-kg`로 구현됨. 자동 구현 제외(중복).
- 검색에 재등장한 2604.03496(trace-kg), 2606.09134(usd2kg), 2606.01208(anchor-cti), 2409.03284(itext2kg), 2503.05388(ollm 계열), 2509.00140(se-standards-zeroshot), 2412.20942(ontology-grounded-wikidata), 2604.20795(llm-external-onto-memory), 2604.23090(multiagent-ontogen) 등은 이미 등록.

## 승인 대기 / 보류 (이번 실행 신규 발견 없음 — 기존 백로그 유지)
- GPU·RL·대용량: agents-k1(2606.13669), agentic-kgr, ark-sail, hgnet, lec-kg, ontokg-routing.
- off-core/멀티모달: agrag, compcq, idea2-cq, industrial-asset-kg, autopkg, llms-graphs-survey(서베이).
- 직접 구현하려면 `/impl-approve <id>` → `/impl-next`.

## 결론
- **이번 실행 자동 구현: 2건(atom-tkg, llms4ol-2025) 게시.** 신규 발표 '구축' 논문은 없었고, 검증된 미등록 on-core MOCK 방법 catch-up으로 채움.
- 사이트 32개로 확장(KO/EN). 로컬 커밋만, push는 사용자가 수동.
