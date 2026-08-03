---
name: evidence-gate
description: "Mandatory gate for any turn that creates or modifies files, runs a state-changing command or tool call (incl. MCP writes and delegated work), or claims work status — however trivial (body scales LIGHT vs FULL). Includes approval turns green-lighting planned work (ㅇㅋ, 진행해, do it) and continuation/post-compaction turns that resume work or claim status (계속, resume). If a read-only turn becomes an edit, load before the first mutation. Not for pure questions or research with no change and no status claim."
---

# evidence-gate — 초안은 제출물이 아니라 검토 대상이다

## 0. 원칙 — 자기보고 무효

모든 판정은 아티팩트(명령 출력, exit code, diff, 파일:라인)가 내린다. 문장은 claim을 아티팩트에 연결할 뿐이다.

보고 끝의 ledger는 **기계 검증 대상**이다. Stop hook(`hooks/eg_audit.py`)이 세션 기록과 대조해 인용한 command의 실행 여부, 인용 줄의 실존, 마지막 mutation 이후인지, 위임 결과를 증거로 쓰지 않았는지를 확인한다. 지어낸 증거는 규범 위반이 아니라 **검출**된다.

세션 내 재로드 불요 — 본문이 컨텍스트에 있으면 로드 없이 따른다. 단 compaction 요약을 거쳤거나 resume으로 시작한 세션이면 이후 첫 게이트 적용 턴에 1회 재로드하고, 그 외에도 §2 done-check 사다리 5단을 원문으로 인용할 수 없으면 유실로 간주해 재로드한다. 지각 로드·유실 후 재로드는 면제가 아니다 — 소급 기준은 §1 래칫을 따른다.

## 1. 규모 판정 — "간단함"은 기분이 아니라 숫자다

**변경의 정의.** 파일·상태를 변이시키는 모든 수단이 변경이다: Edit/Write, shell write, package·lockfile 변이, git working tree·history 조작, 외부 리소스 쓰기, 위임 작업, 상태변경 명령 실행.

**면제.** 조회·설명·검색처럼 변이가 없으면 scale을 생략한다. 조회가 변경으로 바뀌면 첫 mutation 직전에 판정한다. §4의 claim 어휘와 증거 상한은 변경 유무와 무관하게 적용한다.

**판정 단위.** 사용자 요청 전체를 한 번 판정하고 여러 LIGHT로 쪼개지 않는다. 아래가 모두 참일 때만 LIGHT다.

- 파일 1개, 또는 주 파일과 테스트 러너가 수집하는 직접 test pair 1개까지다.
- 따로 확인할 산출물이 2개 이하다.
- public behavior·signature·schema와 외부 상태를 바꾸지 않는다.
- 비가역·보안·비용·PHI·위임 변경이 없다.
- 변경이 심볼 1~2개와 수십 줄 이내이고 별도 판단이 필요 없다.

**래칫.** 그 밖의 다파일, public contract, 외부 write, 고위험 변경, 위임 결과, 판단이 필요한 범위는 FULL이다. 조회→변경, 범위 확장, 편집 파일 밖 caller 발견, 지각 로드는 상향 트리거다. 건너뛴 닻은 원요청에서 소급하고 `done-check 사후 선정`을 표기한다.

선언은 `scale: LIGHT — 파일: <path>[ + <test path>], 요구: "<원문>"` 또는 `scale: FULL — 파일 <n>개, 요구 <n>개`로 남긴다.

**TRIVIAL.** 실행 의미가 없는 단일 파일 산문·주석·오타 변경은 diff로 확인한 content/scope claim에 `INSPECTED`까지만 부여하고 runtime claim을 만들지 않는다.

**고정 안전 규칙.** 편집 전에 대상을 읽는다. 단 `.env`, credentials, private material은 내용을 읽지 말고 targeted edit만 한다. 비가역 작업 직전에는 복구 지점을 만들고 종료 시 임시 백업을 정리한다. harness나 task contract가 금지 shell-write token 목록을 주면 대상 경로를 참조하는 Bash command의 모든 segment에서 그 token을 배제한다(read-only인 `2>/dev/null`도 예외 아님 — inspection은 별도 command나 Read tool로 분리). 단 contract가 exact command를 verbatim으로 명시하면 그것은 그대로 실행한다.

## 2. 본 흐름 — 닻 네 개

FULL은 첫 mutation 전에 네 가지를 고정한다. LIGHT도 범위 baseline과 직접 check는 생략하지 않는다.

1. **요구 목록** — 원요청의 요구 구절을 인용하고 `Q1`, `Q2`처럼 번호를 매긴다. 한 덩어리로 뭉개지 않는다.
2. **done-check** — FULL은 requirement/claim마다 `check + expected observable`을 미리 정한다. 하나의 green test를 전체 완료 증거로 쓰지 않는다.

   **done-check 사다리 5단**: (1) 프로젝트 test runner (2) build/compile (3) parser/lint (4) import-only·dry-run (5) 산출물 존재·형식 확인. 위 단계 중 가능한 가장 강한 check를 고르고, 어느 것도 불가능하면 이유와 해당 claim의 `UNVERIFIED`를 미리 수락한다.

   claim type별 최소 적합성: content/format → scoped diff + 해당 parser·schema·render check / parser·build → 실제 parser·build command / targeted behavior → 그 behavior를 실행하는 targeted test / integration·compatibility → 해당 환경에서의 check / wiring·entrypoint → 기존 caller·registry·entrypoint 관찰(runtime claim이면 실행까지) / external write → 목적지 read-after-write / delegated work → §4 provenance 규칙.
3. **범위 선언** — 정확한 변경 경로를 적고, 첫 mutation 전에 target scope의 `git status --short`(필요 시 scoped diff)를 attribution baseline으로 기록한다. 기존 dirty path를 자기 작업으로 주장하지 않는다. 긴 작업·위임 복귀·compaction 뒤에는 baseline과 편집 대상의 마지막 관찰을 다시 확인하고, 마지막 관찰 뒤 같은 target이 예상 밖으로 바뀌었으면 쓰기를 멈추고 충돌을 보고한다. baseline이 없거나 타 세션 변경과 귀속을 분리할 수 없으면 scope claim은 `UNVERIFIED`다.
4. **결정점 목록** — 합리적 대안이 둘 이상인 갈림길과 추천안을 한 번에 제시하고 명시적 go 전에는 지나가지 않는다. 기존 관례를 그대로 따르는 무선택 지점은 결정점이 아니다.

편집 대상 정의를 먼저 읽고, signature·behavior 변경이면 사용처와 영향 범위를 관찰한다. plan mode에서는 네 닻을 plan에 포함하고 중복 작성하지 않는다.

## 3. 자기검토 패스와 보고

초안 뒤에는 기억을 버리고 다음 세 입력만 다시 읽는다 — 원요청 원문과 `Qn` 매핑 / 마지막 mutation 이후의 scoped diff·status(비 git이면 변경 ledger) / 마지막 mutation 이후의 claim별 check 출력. 누락을 고치면 관련 diff·check를 다시 관찰한다. 고치지 못한 항목은 숨기지 말고 해당 status로 보고한다. 검토 범위는 정확성과 명시 요구이며 요청 밖 리팩터링을 추가하지 않는다.

**보고 형식.** 본문은 평소대로 읽기 좋은 산문으로 쓰고, 최종 메시지 **맨 끝**에 ledger 블록 하나를 붙인다. 산문에서 완료를 주장할 때는 ledger의 status를 넘어서지 않는다.

```text
[evidence-gate]
Changed: `<이번 턴에 실제로 mutate한 path>`, `<...>`      ← 변경 없으면: Changed: 없음
Scale: FULL — <근거>                                      ← 사전 선언했으면 생략
Coverage: Q1→C1/E1; Q2→C2(UNVERIFIED)                     ← FULL만
Claims:
- C1 VERIFIED — E1 (<실행해 관찰한 runtime behavior>)
- C2 INSPECTED — E2 (<diff·파일로 확인한 내용·범위>; `<baseline-dirty-path>`는 기존 변경이며 이번 턴에 변경하지 않았다)
- C3 UNVERIFIED (<요청됐으나 실행하지 못한 것과 사유>)
Evidence:
- E1 `<exact command>` (cwd: `<cwd>`, exit 0) — "<결정적 출력 한 줄 verbatim>"
- E2 Read `<path>` — "<관찰한 한 줄>"
Unverified/failed:
- C3 — <사유>; next: <아직 수행하지 않은 action>
```

`Changed:`에는 이번 턴에 실제로 바꾼 경로만 backtick으로 감싸 나열한다(설명·unchanged path 금지 — 설명은 claim으로). 빈 섹션은 `Evidence: 없음`처럼 한 줄로 합친다. 세션 내 앞선 관찰을 재사용하는 evidence는 `E3 (reused) ...`로 표시하며, 재사용 evidence는 `VERIFIED`를 뒷받침하지 못한다(`INSPECTED`까지). `UNVERIFIED`나 `FAILED`가 하나라도 있으면 `Unverified/failed`를 `없음`으로 쓰지 않고 전체 완료를 선언하지 않는다. TRIVIAL은 diff-backed `INSPECTED`만 보고한다.

## 4. 증거와 어휘 — 무엇이 "사실"인가

**Claim-strength contract: evidence strength caps claim strength.** 각 claim은 다음 네 status 중 하나만 쓴다.

- `VERIFIED` — 해당 claim의 예상 observable을 실제 실행해 관찰했다.
- `INSPECTED` — diff/file/static state를 직접 관찰했지만 runtime behavior는 실행하지 않았다.
- `UNVERIFIED` — 적합한 check를 실행하지 못했거나 필요한 환경이 없었다.
- `FAILED` — 적합한 check가 실행됐고 예상 observable과 불일치했거나 check가 실패했다.

Content/change/scope claim은 diff·file·static state에 관한 것이므로 `INSPECTED`에 둔다. Passing behavior test는 실행한 runtime behavior만 `VERIFIED`로 만들며 편집 사실이나 변경 범위까지 승격하지 않는다. static inspection만으로 runtime claim을 `VERIFIED`라 하지 않는다. dry-run은 plan만 검증하고 applied state를 검증하지 않는다. 축소·대체 check는 원 claim을 승격하지 않고 실제로 관찰한 더 좁은 claim만 판정한다.

실행하지 않은 환경·플랫폼에는 `UNVERIFIED` claim과 그 `Unverified/failed` 항목만 쓴다. `should work`, `동일하게 동작할 것`, `likely portable` 같은 예측은 disclaimer가 붙어도 쓰지 않는다.

**증거 자격.** evidence는 claim의 mutation·dependency set에 영향을 준 마지막 mutation 이후의 **부모 세션 직접 관찰**이어야 한다. 관찰 source가 그 set 밖이고 이후 package·version·config·environment 변화가 없으면 세션 내 앞선 관찰을 `(reused)` 표시와 함께 `INSPECTED` evidence로 재사용할 수 있으나, 이 예외로 runtime claim을 `VERIFIED`로 올리지 않는다.

worker summary, 다른 LLM의 판정, 기억, 위치만 적은 citation은 증거가 아니다. **위임 결과는 부모 세션이 diff와 해당 check를 직접 다시 관찰해야 한다**(parent re-observation) — 워커가 인용한 테스트 출력을 그대로 옮기는 것은 증거가 아니며 hook이 검출한다. external write는 목적지를 read-after-write로 관찰해야 하고 write 요청의 성공 응답만으로 applied state를 주장하지 않는다.

각 evidence entry에는 exact command, 모호할 때 cwd, exit code, 판정에 필요한 **한 줄** verbatim output을 넣는다. 여러 줄을 합치거나 요약·정규화하지 않는다(기계 대조가 깨진다). 기존 identifier·path·flag, impact/caller, wiring/entrypoint claim도 실제 정의·사용처·entrypoint 관찰에 연결한다.

## 5. 막혔을 때 — 같은 문을 세 번 두드리지 않는다

동일 에러·증상 2회 실패 = 2-strike — 명령이 달라도 같은 접근이면 같다. 에러가 명시적으로 일시성(timeout·lock·connection reset)을 가리키면 사유 1줄과 함께 1회 추가 재시도만 허용한다.

2-strike 후에는 진단 블록을 실행한다: 에러 원문 인용 + 서로 다른 가설 2개 이상 + 가설을 가를 실험 1개. 실험 출력 원문을 인용하고 어느 가설이 지지·기각됐는지 판정한 뒤에만 다음 수정을 시도하며, 다음 시도는 살아남은 가설을 명시적으로 인용한다. 그래도 같은 지점이면 fresh-context subagent에 문제 서술과 에러 원문만 주고 새로 보게 하거나, 막힌 지점을 보고하고 `/cross-verify`를 제안한다.

## 6. 외부 검증 — 자기 가중치의 맹점 밖으로

아래 신호가 하나라도 있으면 자기검토 뒤 `/cross-verify`를 제안한다(자동 실행하지 않는다) — 비가역 작업(마이그레이션·대량 삭제·force push) / 보안·비용·PHI 경로 / 3개 이상 파일의 구조 변경 / `FAILED`를 고쳤지만 파급 범위가 불확실할 때. 신호가 무겁게 겹치면 `/deep-verify`를 제안한다.

무료 대안은 fresh-context verifier다. 원요청, `Qn`·claim·expected observable, scoped diff·status, check 출력만 주고 빌더의 결론은 주지 않는다. verifier 결과에도 §4를 그대로 적용한다.

finding 처리: 재현을 먼저 시도하고, 재현되면 재현 증거를 첨부해 수정 여부를 사용자에게 묻는다. 기각에는 반증 증거(코드 인용 또는 실행 출력)가 필요하다 — "그럴 것 같지 않다"는 기각 사유가 아니다. 정확성·명시 요구와 무관한 개선 제안은 고치지 않고 목록으로 전달한다. `/cross-verify` 실행 중이면 그 스킬의 합의 루프가 우선한다.

## 7. 경계 — 기존 규범·다른 절차와의 관계

메모리·harness가 이미 커버하는 규범(결정점 사용자 확인, 한국어 산문+영어 코드, 사실/추정 라벨, 잔여물 정리, git 규칙)은 재규정하지 않으며 실제 충돌 시 그쪽이 우선한다. 우선권 발동에는 충돌하는 양쪽 문장의 인용이 필요하다 — 인용 없는 충돌 주장은 무효다.

분업: design-agent/implement-agent 워크플로우의 자체 게이트·검증 계약이 절차를 지배하고 이 스킬은 §4 claim-strength 계약만 적용한다. 사용자가 `/verify`, `/code-review`, `/cross-verify`를 명시 호출하면 그 절차가 우선한다.
