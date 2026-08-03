# DESIGN — evidence-gate v2: 선언/판정 분리 (declare / enforce split)

- 날짜: 2026-07-29
- 상태: **설계 검토 대기** (작성자 승인 전 구현 금지)
- 대상 버전: skill v2.0.0 (보고 형식이 바뀌므로 breaking)
- 승인된 방향 (2026-07-29 대화): 방향 A(선언/판정 분리) + 보고형식 완화(산문 + ledger 블록) + warn-only 시작

## 0. 한 줄 요약

스킬 본문은 "주장 등급 + 증거 표기" 계약만 남기고 절반으로 줄이고, 검증은 턴 종료 시 자동 실행되는 결정적 스크립트(Stop hook)가 세션 기록(transcript `.jsonl`)을 대조해 집행한다. 위조·재탕·타 에이전트 보고 인용을 기계적으로 차단하고, 모델 추론에는 개입하지 않는다.

## 1. 배경 — 측정된 문제

- v1 eval(`evidence_gate_eval/REPORT.md`, 2026-06-11): 정확성 한계효용 ≈ 0 (3과제 모두 스킬 유무 무관 9/9 천장), 오버헤드 토큰 +55% / 시간 +46% (v1.0 본문·소형 과제 기준). 가치 축은 증거생산(신뢰성·감사성)으로 확인.
- 구조 한계: 전 규칙이 자기보고다. "안 해놓고 VERIFIED"를 차단하지 못한다 — evidence 항목(E#)도 지어낼 수 있고 대조 주체가 없다. 위임 결과의 parent re-observation(부모 세션 직접 재관찰)도 규범일 뿐 강제가 아니다.
- 형식 기계(v1.1 §3의 final-send preflight, report terminator, 첫-토큰 `Changed:` 강제)가 harness의 산문 보고 지침과 충돌하고, 출력 오버헤드와 가독성 비용의 주범이다.

## 2. 목표 / 비목표

목표:
- G1. 거짓·부실 보고의 **기계적 검출** — 존재(실행됐나) · 시점(마지막 수정 이후인가) · 출처(직접 관찰인가).
- G2. 컨텍스트·출력 오버헤드 절감 — 본문 ≤ 현행의 약 50%, 보고 의례를 산문 + ledger 블록 1개로 완화.
- G3. 추론 간섭 0 — 판정은 턴 끝에서만, 모델 토큰 소비 0.
- G4. 위임 자기보고의 기계적 배제 — worker의 "됐다"는 증거 자격 없음을 스크립트가 강제.

비목표:
- semantic 적절성 판정("그 check가 그 claim에 적합한가")은 범위 밖 — 모델 규율 + cross-verify 몫.
- 워커 세션 내부 감시 — 부모 세션 복귀 시점(재관찰 요구)에서 잡는다. (Claude 서브에이전트에 동일 감사를 붙이는 SubagentStop은 Phase 2)
- 형식 완벽주의 — hook이 잡을 수 있는 것은 hook에 맡기고 본문 규칙에서 뺀다.

## 3. 아키텍처

```
[선언 — 모델 컨텍스트]                [판정 — 모델 밖]
SKILL.md v2 (계약)          ←문법 공유→   hooks/eg_audit.py (Stop hook)
- 4-status + caps 규칙                  - transcript .jsonl 파싱
- ledger 문법(§5)                        - ledger 추출 → tool 기록과 대조(R1~R6)
- parent re-observation                  - 위반: block 모드=차단+사유 / warn 모드=로그
```

두 컴포넌트의 유일한 접점은 **ledger 문법(§5)**이다. SKILL.md와 auditor가 같은 문법 스펙(부록 A)을 참조한다.

## 4. 컴포넌트 A — SKILL.md v2 (다이어트)

| 처리 | 대상 (v1.1 기준) |
|---|---|
| 유지(슬림화) | §0 자기보고 무효 / §1 scale 판정(LIGHT·FULL·TRIVIAL)과 고정 안전 규칙 / §2 닻 4개(Qn 요구 목록·done-check 사다리 5단·범위 baseline·결정점) / §3 앞부분 자기검토 패스(기억 버리고 3입력 재독) / §4 4-status·evidence caps claim·한 줄 verbatim·parent re-observation·read-after-write / §5 2-strike / §6 cross-verify 트리거 / §7 경계 |
| 제거 | §3 final-send preflight, report terminator, 첫-토큰 `Changed:` 강제, "`Changed:` 앞 prose 금지" 계열 전부, 미실행 환경 어휘 금지 조항의 세부 나열(4-status 계약이 커버) |
| 완화 | 보고 = **자유 산문 + 최종 메시지 끝에 ledger 블록 1개**(§5 문법). Changed / Claims / Evidence / Unverified·failed 는 ledger 안에 유지. Coverage는 FULL만 |

목표 분량: 본문 ≤ 90줄 (현 171줄). 어휘 계약의 핵심 문장("evidence strength caps claim strength", 4-status 정의)은 원문 유지 — 글로벌 CLAUDE.md의 캐너리 인용 조건이 이 문장을 가리킨다(P5에서 동기화 확인).

## 5. Ledger 문법 — hook 파싱 계약

최종 메시지의 **마지막**에 아래 블록 하나. `[evidence-gate]` 마커 줄로 시작한다(산문 허용 후 블록 경계를 결정적으로 찾기 위한 장치).

```text
[evidence-gate]
Changed: `<path>`[, `<path>`...]        ← 이번 턴 실제 mutate한 경로만 / 없으면: Changed: 없음
Scale: FULL — <basis>                   ← 선택(사전 선언했으면 생략)
Coverage: Q1→C1/E1; Q2→C2(UNVERIFIED)   ← FULL만
Claims:
- C1 VERIFIED — E1 (<runtime claim>)
- C2 INSPECTED — E2 (<content/scope claim>)
- C3 UNVERIFIED (<사유>)
- C4 FAILED — E3 (<불일치 내용>)
Evidence:
- E1 `<exact command>` (cwd: `<cwd>`, exit <n>) — "<결정적 출력 한 줄>"
- E2 Read `<path>` — "<관찰한 한 줄>"
- E3 (reused) `<command>` (exit <n>) — "<한 줄>"    ← 이전 관찰 재사용 표시
Unverified/failed:
- C3 — <사유>; next: <아직 수행하지 않은 액션>
```

- 빈 섹션은 `Evidence: 없음`처럼 한 줄로 합친다.
- `(reused)` = 세션 내 앞선 직접 관찰의 재사용(v1.1 §4 재사용 예외). **VERIFIED를 뒷받침할 수 없다**(INSPECTED까지) — R4가 기계 강제.
- 정규식 스펙은 부록 A. SKILL.md v2에는 이 문법의 예시 블록만 싣고 정규식은 싣지 않는다(모델용 문서와 구현용 스펙 분리).

## 6. 컴포넌트 B — Auditor 검사 규칙 (R1~R6)

전제 수집 (transcript에서):
- (a) 최종 assistant 텍스트 (이번 턴 = 마지막 실제 user 메시지 이후 구간)
- (b) 세션 전체 tool_use / tool_result 시퀀스 (순서 보존)
- (c) mutation 이벤트: Edit / Write / NotebookEdit tool_use(`file_path`) + Bash 중 write-패턴 휴리스틱(부록 B)

| 규칙 | 내용 | 위반 시 |
|---|---|---|
| R1 ledger 존재 | 이번 턴에 mutation 이벤트가 있는데 최종 메시지에 `[evidence-gate]` 블록이 없다 | warn급 (라벨 회피 경로 차단) |
| R2 실행 실재 | VERIFIED/INSPECTED가 참조한 E#의 command와 일치하는 Bash tool_use(또는 Read의 `file_path`)가 세션에 실존해야 함. 매칭: 공백 정규화 후 완전일치 → 실패 시 느슨한 포함 매칭은 "loose"로 기록(부록 A) | violation |
| R3 인용 실재 | E#의 "결정적 출력 한 줄"이 그 tool_use의 tool_result 텍스트에 부분 문자열로 실존해야 함 | violation (= 위조) |
| R4 시점 freshness | VERIFIED claim의 매칭 tool_use는 `Changed:` 목록 경로들의 마지막 mutation 이벤트 **이후**여야 함. `(reused)` evidence는 VERIFIED 뒷받침 불가 | violation (재탕 차단) |
| R5 출처 | 매칭 tool_result가 위임 도구(Agent/Task/Workflow, `mcp__codex__*`, `mcp__gemini__*`) 결과이거나, Bash command가 위임 CLI 패턴(부록 B: `grok`, `codex`, `gemini`, `claude -p`, `orca orchestration` 등)이면 VERIFIED/INSPECTED 증거로 불인정 | violation ("남의 보고는 증거가 아니다"의 기계화) |
| R6 루프 안전 | `stop_hook_active=true`면 차단하지 않고 warn으로 강등. 턴당 최대 1회 차단 | — |

위반 처리:
- **warn 모드(초기 1~2주)**: 차단 없음. `~/.claude/evidence-gate/audit.log`에 JSON 한 줄 기록(턴 id·규칙·상세). 오탐율 측정용.
- **block 모드**: `{"decision":"block","reason":"R3 위반: E1 인용 줄이 세션 기록에 없음 — 해당 check를 실제로 실행하거나 claim을 UNVERIFIED로 정정하라"}` 반환 → 모델이 같은 턴에서 정정. R6에 의해 정정 후 재시도는 차단하지 않음(두 번째 거짓은 통과되지만 로그에 남는다 — v1 수용 한계).
- 모드 설정: `~/.claude/evidence-gate/config.json` `{"mode": "warn"}` (env var 대신 파일 — 세션 무관 일관).
- **fail-open 원칙**: 파서 예외·transcript 스키마 변화 시 무조건 통과 + 에러 로그. hook이 세션을 벽돌로 만들면 안 된다.

## 7. 명시적 한계 (수용하고 문서화)

1. semantic 적절성은 못 잡는다 — "빌드 성공"을 behavior 테스트 없이 VERIFIED로 다는 종류는 모델 규율 + cross-verify 몫. hook의 과녁은 존재·시점·출처 위반("안 해놓고 했다")이다.
2. Bash로 감싼 위임(`grok -p ...` 등)은 블록리스트 휴리스틱 — 새 위임 CLI 도입 시 목록 갱신 필요(config에서 확장 가능하게).
3. 산문 속 자연어 완료 주장("다 됐다")은 R1(ledger 부재)로만 간접 탐지 — 자연어 어휘 검열은 오탐 과다로 제외.
4. transcript 스키마는 Claude Code 내부 형식 — 버전업에 깨질 수 있음 → 방어적 파싱 + fail-open + 로그.
5. INSPECTED의 freshness는 미검사(재사용 예외의 "mutation set 밖" 판정이 기계화 불가) — VERIFIED만 R4 적용.
6. resume·compaction 세션에서 transcript가 이전 기록을 완전 포함하지 않으면 R2가 오탐할 수 있음 — 구현 시 실측, 의심 시 fail-open.
7. Stop hook 계약(입력 JSON의 `transcript_path`·`stop_hook_active`, exit 2/`decision:block` 차단)은 문서 기준 — P1에서 실측 확인이 첫 작업.

## 8. 시행 계획

- **P0** 이 문서 승인 (작성자) — 미결 결정점 D1~D5 포함 일괄 확정.
- **P1** 구현: SKILL.md v2 재작성 + `hooks/eg_audit.py`(python3 stdlib only) + 단위테스트(fixture transcript 4종: 위조 인용 / 재탕 / 워커 인용 / 정상). 구현은 sonnet 또는 Codex 위임(POST_FABLE_OPS §1.1), 설계·리뷰는 메인 세션.
- **P2** 검증: (a) auditor 단위테스트 (b) 적대 게이밍 — R2~R5 각각에 우회 시도 최소 1건씩 만들어 전부 잡히는지 (c) cross-verify(Codex) — 집행 기계라 고위험 (d) `evidence_gate_eval` v2 8종 중 2~3종 스모크(퇴화 감지 기준선 용도, 2026-07-08 보관 결정과 부합).
- **P3** 배포: `~/.claude/settings.json`에 Stop hook 등록(update-config 절차) + SKILL v2 설치(`~/.claude/skills/evidence-gate/`) + repo 커밋·태그(v2.0.0)는 작성자 요청 시.
- **P4** warn-only 1~2주 운용 → `audit.log` 리뷰(오탐율·실탐 사례) → block 승격 여부 결정. 재검토일: 2026-08-12.
- **P5** 글로벌 CLAUDE.md 게이트 문구 동기화 — §2 사다리·§4 계약 캐너리 문장이 v2에도 존재하는지 확인, 보고형식 관련 문구 조정.

## 9. 미결 결정점 (P0에서 확정) — 추천 포함

- **D1 freshness 기준**: `Changed:` 목록 경로의 마지막 mutation 기준(추천 — 오탐 적음) vs 세션 전체 mutation 기준(엄격하나 무관 편집에 오탐).
- **D2 위임 블록리스트 초기 목록**: 부록 B 초안대로 시작(추천), config로 확장.
- **D3 ledger 마커**: `[evidence-gate]` 고정 문자열(추천 — 산문과 결정적 분리) vs `Changed:`를 마커로 재사용(산문 충돌 위험).
- **D4 warn 모드 알림**: 로그만 조용히(추천 — 소음 최소, 주간 리뷰) vs 위반마다 사용자 알림.
- **D5 SubagentStop(Claude 워커 동일 감사)**: Phase 2로 미룸(추천) vs P1에 포함.

## 부록 A — ledger 정규식 스펙 (구현 기준 초안)

```python
BLOCK_START = r'^\[evidence-gate\]\s*$'
CHANGED     = r'^Changed:\s*(없음|`[^`]+`(?:,\s*`[^`]+`)*)\s*$'
SCALE       = r'^Scale:\s*(LIGHT|FULL)\s*—\s*(.+)$'
COVERAGE    = r'^Coverage:\s*(.+)$'
CLAIM       = r'^-\s*(C\d+)\s+(VERIFIED|INSPECTED|UNVERIFIED|FAILED)(?:\s+—\s+(E\d+(?:,\s*E\d+)*))?\s*\((.*)\)\s*$'
EV_CMD      = r'^-\s*(E\d+)\s*(\(reused\))?\s*`(.+?)`\s*\((?:cwd:\s*`([^`]+)`,\s*)?exit\s+(\d+)\)\s*—\s*"(.*)"\s*$'
EV_READ     = r'^-\s*(E\d+)\s*(\(reused\))?\s*Read\s+`([^`]+)`\s*—\s*"(.*)"\s*$'
```

검증 매핑:
- VERIFIED/INSPECTED claim은 E-참조 필수, 참조된 E#는 Evidence 섹션에 실존해야 함(하나라도 깨지면 해당 claim 위반).
- command 매칭: `' '.join(cmd.split())` 정규화 후 완전일치. 실패 시 포함 매칭(cited ⊂ executed 또는 역방향)은 통과시키되 `loose`로 로그 — block 모드에서도 loose는 차단하지 않음(오탐 방지).
- 인용 줄 매칭: 공백 정규화 후 부분 문자열. exit code 대조는 best-effort(tool_result에 기계적 exit 필드가 없으면 생략).
- 턴 경계: 마지막 "실제 user 메시지"(tool_result 아닌 user role) 이후를 이번 턴으로 본다.

## 부록 B — mutation 휴리스틱·위임 블록리스트 (초안, P1에서 fixture로 실측 조정)

```python
MUTATION_TOOLS = {"Edit", "Write", "NotebookEdit"}          # input.file_path 수집
BASH_WRITE_HINTS = [                                         # 오탐 주의: 2>/dev/null, >/dev/null 류 제외
    r'(?<![2&])>(?!/dev/null)', r'\btee\b', r'\bsed\s+-i\b', r'^\s*(mv|cp|rm|mkdir|touch|chmod|ln)\b',
    r'\bgit\s+(commit|checkout|reset|merge|rebase|apply|cherry-pick|stash|push)\b',
    r'\b(npm\s+(i|install|update)|pip3?\s+install)\b',
]
DELEGATION_TOOLS = {"Agent", "Task", "Workflow"}             # + mcp__codex__*, mcp__gemini__*
DELEGATION_BASH  = [r'^\s*(grok|codex|gemini)\b', r'^\s*claude\s+(-p|--print)\b', r'\borca\s+orchestration\b']
```

## 10. 검증 성공 기준 (P2 통과 조건)

1. fixture 4종에서 정확 판정(위조→R3, 재탕→R4, 워커 인용→R5, 정상→무위반).
2. 적대 게이밍 시도 전부 검출(R2~R5 각 1+).
3. cross-verify 합의 도달(미해결 BLOCKER 0).
4. v2 스모크 태스크에서 v1.1 대비 준수 유지 + 보고 토큰 감소 관찰(방향성 확인이면 충분, 엄밀 A/B는 비목표).
