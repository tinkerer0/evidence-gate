---
name: evidence-gate
description: "Mandatory gate for any turn that creates or modifies files, runs a state-changing command or tool call (incl. MCP writes and delegated work), or claims work status — however trivial (body scales LIGHT vs FULL). Includes approval turns green-lighting planned work (ㅇㅋ, 진행해, do it) and continuation/post-compaction turns that resume work or claim status (계속, resume). If a read-only turn becomes an edit, load before the first mutation. Not for pure questions or research with no change and no status claim."
---

# evidence-gate — 초안은 제출물이 아니라 검토 대상이다

## 0. 원칙 — 자기보고 무효

모든 판정은 아티팩트(명령 출력, exit code, diff, 파일:라인)가 내린다. 문장은 claim을 아티팩트에 연결할 뿐이다.

세션 내 재로드 불요 — 본문이 컨텍스트에 있으면 로드 없이 따른다. 단 compaction 요약을 거쳤거나 resume으로 시작한 세션이면 이후 첫 게이트 적용 턴에 1회 재로드하고, 그 외에도 §2 done-check 사다리 5단을 원문으로 인용할 수 없으면 유실로 간주해 재로드한다.

지각 로드(late-entry)·유실 후 재로드는 면제가 아니다: 소급 기준과 보고 표기는 §1 래칫을 따른다.

## 1. 규모 판정 — "간단함"은 기분이 아니라 숫자다

**변경의 정의.** 파일·상태를 변이시키는 모든 수단이 변경이다: Edit/Write, shell write, package·lockfile 변이, git working tree·history 조작, 외부 리소스 쓰기, 위임 작업. 상태변경 명령 실행도 포함한다.

**면제.** 조회·설명·검색처럼 변이가 없으면 scale을 생략한다. 조회가 변경으로 바뀌면 첫 mutation 직전에 판정한다. §4의 claim 어휘와 증거 상한은 변경 유무와 무관하게 적용한다.

**판정 단위.** 사용자 요청 전체를 한 번 판정하고 여러 LIGHT로 쪼개지 않는다. 아래가 모두 참일 때만 LIGHT다.

- 파일 1개, 또는 주 파일과 테스트 러너가 수집하는 직접 test pair 1개까지다.
- 따로 확인할 산출물이 2개 이하다.
- public behavior·signature·schema와 외부 상태를 바꾸지 않는다.
- 비가역·보안·비용·PHI·위임 변경이 없다.
- 변경이 심볼 1~2개와 수십 줄 이내이고 별도 판단이 필요 없다.

**래칫.** 그 밖의 다파일, public contract, 외부 write, 고위험 변경, 위임 결과, 판단이 필요한 범위는 FULL이다. 조회→변경, 범위 확장, 편집 파일 밖 caller 발견, late-entry는 상향 트리거다. 건너뛴 닻은 원요청에서 소급하고 `done-check 사후 선정`을 표기한다.

선언은 `scale: LIGHT — 파일: <path>[ + <test path> (짝: test pair)], 요구: "<원문>"` 또는 `scale: FULL — 파일 <n>개, 요구 <n>개`로 남긴다.

**TRIVIAL.** 실행 의미가 없는 단일 파일 산문·주석·오타 변경은 diff로 확인한 content/scope claim에 `INSPECTED`까지만 부여한다. runtime claim을 만들지 않는다.

**고정 안전 규칙.** 편집 전에 대상을 읽는다. 단 `.env`, credentials, private material은 내용을 읽지 말고 targeted edit만 한다. 비가역 작업 직전에는 복구 지점을 만들고 종료 시 임시 백업을 정리한다.

**Enclosing harness tool boundary.** harness나 task contract가 금지 shell-write construct/token 목록을 주면, contract-listed target path를 참조하는 Bash command의 모든 segment에는 그 token을 하나도 넣지 않는다. read-only stderr suppression인 `2>/dev/null`도 예외가 아니다. inspection은 별도 command로 나누거나 Read tool을 사용하고, 목록에 없는 safe exception을 추론하지 말고 literal tool boundary를 따른다. 단 contract가 exact command를 verbatim으로 명시하면 그 command는 정확히 그대로 실행하며, 이 token rule은 명시적으로 mandated exact command를 override하지 않는다.

## 2. 본 흐름 — 닻 네 개

FULL은 첫 mutation 전에 네 가지를 고정한다. LIGHT도 범위 baseline과 직접 check는 생략하지 않는다.

1. **요구 목록** — 원요청의 요구 구절을 인용하고 `Q1`, `Q2`처럼 번호를 매긴다. 한 덩어리로 뭉개지 않는다.
2. **done-check** — FULL은 requirement/claim마다 `check + expected observable`을 미리 정한다. 하나의 green test를 전체 완료 증거로 쓰지 않는다.

   **done-check 사다리 5단**: (1) 프로젝트 test runner (2) build/compile (3) parser/lint (4) import-only·dry-run (5) 산출물 존재·형식 확인. 위 단계 중 가능한 가장 강한 check를 고르고, 어느 것도 불가능하면 이유와 해당 claim의 `UNVERIFIED`를 미리 수락한다.

   claim type별 최소 적합성은 다음과 같다.

   - content/format → scoped diff와 해당 parser·schema·render check
   - parser/build → 실제 parser·build command
   - targeted behavior → 해당 behavior를 실행하는 targeted test
   - integration/compatibility → 해당 integration·환경에서의 check
   - wiring/entrypoint → 기존 caller·registry·entrypoint 관찰, runtime claim이면 실행까지
   - external write → 목적지 read-after-write
   - delegated work → §4 provenance 규칙
3. **범위 선언** — 정확한 변경 경로를 적고, 첫 mutation 전에 target scope의 `git status --short`와 필요 시 scoped diff/name list를 attribution baseline으로 기록한다. 기존 dirty path를 자기 작업으로 주장하지 않는다. 긴 작업, 위임 복귀, compaction 뒤에는 이 baseline과 편집 대상의 마지막 관찰을 concurrent-change recheck로 다시 확인한다. 마지막 관찰 뒤 같은 target이 예상 밖으로 바뀌면 쓰기를 멈추고 충돌을 보고한다. baseline이 없거나 타 세션 변경과 귀속을 분리할 수 없으면 scope claim은 `UNVERIFIED`다.
4. **결정점 목록** — 합리적 대안이 둘 이상인 갈림길과 추천안을 한 번에 제시하고 명시적 go 전에는 지나가지 않는다. 기존 관례를 그대로 따르는 무선택 지점은 결정점이 아니다.

편집 대상 정의를 먼저 읽고, signature·behavior 변경이면 사용처와 영향 범위를 관찰한다. plan mode에서는 네 닻을 plan에 포함하고 중복 작성하지 않는다.

## 3. 자기검토 패스 — 초안 직후, 보고 직전

초안 뒤에는 기억을 버리고 다음 세 입력만 다시 읽는다.

- 원요청 원문과 `Qn` 매핑
- 마지막 mutation 이후의 scoped diff/status 또는 비 git 변경 ledger
- 마지막 mutation 이후의 claim별 check 출력

누락을 고치면 관련 diff/status/check를 다시 관찰한다. 고치지 못한 항목은 숨기지 말고 해당 status로 보고한다. 검토 범위는 정확성과 명시 요구이며 요청 밖 리팩터링을 추가하지 않는다.

**공통 report boundary.** 최종 top-level 응답은 산문·제목·preamble 없이 첫 줄부터 `Changed:`로 시작한다. 첫 줄에는 이번 턴에 실제로 mutate한 path만 각각 backtick으로 감싸 comma-separated로 쓰거나, 변경이 없으면 정확히 `Changed: 없음`만 쓴다. 이 줄에 설명·괄호·귀속 문구·unchanged path를 넣지 말고 모두 아래 claim/evidence entry로 내린다. acknowledgement, attribution 설명, status recap을 포함한 어떤 prose도 `Changed:` 앞에 둘 수 없다.

**Mandatory final-send preflight.** report-producing final은 prose draft가 아니라 아래 canonical block에서 직접 조립한다. 첫 emitted token은 literal `Changed:`여야 하고 첫 non-whitespace line도 `Changed:` line이어야 한다. send 직전에 첫 non-whitespace line을 기계적으로 검사한다. 그것이 `Changed:` line이 아니면 최초 `Changed:` line 앞의 모든 line을 삭제하고 다시 검사하며, 기존 prose 아래에 report를 하나 더 append하는 방식으로 고치지 않는다. 삭제한 prose에 다른 곳에 없는 required content가 있었다면 버리지 말고 적절한 claim/evidence entry로 옮긴 뒤 재검사한다. 이 preflight는 report-producing final에만 적용하며 pre-work decision point, diagnostic, 그 밖의 non-report turn에는 적용하지 않는다.

**Scale placement.** scale을 mutation 전 non-final turn에서 이미 선언했다면 report final에서 반복하지 않는다. 그런 선언이 없고 final에 scale을 포함한다면 정확히 한 줄의 `Scale: LIGHT — ...` 또는 `Scale: FULL — ...`만 허용하며, `Changed:` 바로 뒤이자 `Coverage:`/`Claims:` 앞이 유일한 위치다.

**Report terminator.** report를 생성하는 turn의 final top-level response 전체가 report block이다. LIGHT는 마지막 `Unverified/failed` content 직후, FULL은 마지막 `cross-verify:` line 직후 종료한다. 그 뒤에 heading, recap, appendix, “honest answer”, caveat, 또는 어떤 prose도 추가하지 않는다. 이 규칙은 pre-work decision point, diagnostic, non-report turn을 억제하지 않는다.

**Claim ledger.** Runtime behavior, static content/change/scope, 명시적으로 요청됐지만 실행하지 않은 environment/platform은 서로 다른 atomic claim이다. Claim ID는 보고에 존재하는 status만 `VERIFIED` → `INSPECTED` → `UNVERIFIED` → `FAILED` 순서로 배정한다. status와 evidence entry를 모두 공유하는 claim은 합친다. 모든 `VERIFIED`와 `INSPECTED` claim은 실제로 존재하는 `E#`를 참조해야 하며 file/line이나 산문만 인용할 수 없다. 논의하는 baseline-dirty path의 귀속 설명은 적용 가능한 `INSPECTED` scope claim 안에만 두고, 그 claim에 literal `pre-existing` 또는 `기존 변경`과 "이번 턴에는 변경하지 않았다"는 진술을 함께 넣는다. 별도 claim이나 report 앞 prose로 밀어내지 않는다. "already present"나 "세션 시작부터 있었다"만으로는 귀속되지 않는다.

명시적으로 요청된 모든 environment/platform은 claim ledger에 남긴다. 명시적으로 물은 미실행 environment/platform의 답은 해당 `UNVERIFIED` claim과 그 `Unverified/failed` entry에만 둔다. ledger 뒤에서 답을 재서술하지 않는다. `should work`, `behave the same`, `identical`, `likely portable` 또는 동등한 prediction은 `not verified`, `expectation` 같은 disclaimer가 붙어도 금지한다. 미실행 environment를 이름 붙인 line에는 `UNVERIFIED` status token과 execution이 일어나지 않았다는 사실만 쓰고, `VERIFIED`, `not verified`, `검증됨`, `확인 완료`, `아직 검증 안 됨`처럼 positive, negated, hedged completion vocabulary를 쓰지 않는다. `UNVERIFIED`나 `FAILED` claim이 하나라도 있으면 `Unverified/failed`에 `C#`, 이유, 다음 check를 적고 `없음`이라 쓰지 않는다. 다음 check는 `run <check> in <env>`처럼 아직 수행하지 않은 action으로만 표현한다.

각 evidence entry는 exact command, 모호할 때 cwd, exit code와 도구가 내보낸 decisive output **한 줄**의 verbatim quote만 담는다. 여러 줄을 합치거나 line break를 literal `\\n`으로 쓰거나 normalize·요약하지 않는다.

**LIGHT canonical example (placeholder-only; Scale line은 위 조건에서만 optional; 마지막 표시 줄이 report terminator)**

```text
Changed: `<current-turn-path>`, `<current-turn-test-path>`
Scale: LIGHT — `<optional-scale-basis>`
Claims:
- C1 VERIFIED — E1 (<tested-runtime-behavior>)
- C2 INSPECTED — E2 (<static-change-and-scope>; `<baseline-dirty-path>` is pre-existing and was not changed in the current turn)
- C3 UNVERIFIED (execution did not occur in `<requested-environment>`)
Evidence:
- E1 `<behavior-check>` (cwd: `<cwd>`, exit 0) — "<one-decisive-output-line>"
- E2 `<scope-check>` (cwd: `<cwd>`, exit 0) — "<one-decisive-output-line>"
Unverified/failed:
- C3 UNVERIFIED — execution did not occur in `<requested-environment>`; next check: run `<environment-check>` in `<requested-environment>`.
```

**FULL 보고 형식 (placeholder-only; Scale line은 위 조건에서만 optional; 마지막 표시 줄이 report terminator)**

```text
Changed: `<current-turn-path-a>`, `<current-turn-path-b>`
Scale: FULL — `<optional-scale-basis>`
Coverage: Q1→C1/E1; Q2→C2/E2; Q3→C3(UNVERIFIED)
Claims:
- C1 VERIFIED — E1 (<tested-runtime-behavior>)
- C2 INSPECTED — E2 (<static-change-and-scope>)
- C3 UNVERIFIED (execution did not occur in `<requested-environment>`)
Evidence:
- E1 `<behavior-check>` (cwd: `<cwd>`, exit 0) — "<one-decisive-output-line>"
- E2 `<scope-check>` (cwd: `<cwd>`, exit 0) — "<one-decisive-output-line>"
Unverified/failed:
- C3 UNVERIFIED — execution did not occur in `<requested-environment>`; next check: run `<environment-check>` in `<requested-environment>`.
cross-verify: 해당 없음 (§6 트리거 불충족) | 제안 — <trigger>
```

두 형식 모두 `Changed`, `Claims`, `Evidence`, `Unverified/failed`를 포함한다. 빈 섹션은 `Evidence: 없음`처럼 한 줄로 합친다. FULL은 모든 요구를 `Coverage: Q1→C1/E1; Q2→C2/E2; ...`로 연결하고 evidence가 없으면 `Qn→Cn(UNVERIFIED)`로 남긴다. LIGHT에는 `Coverage`와 `cross-verify`를 강제하지 않는다.

TRIVIAL은 diff-backed `INSPECTED`만 보고한다. `UNVERIFIED`나 `FAILED`가 하나라도 있으면 전체 완료를 선언하지 않고 부분 성공으로 쓴다.

## 4. 증거와 어휘 — 무엇이 "사실"인가

**Claim-strength contract: evidence strength caps claim strength.** 각 claim은 다음 네 status 중 하나만 쓴다.

- `VERIFIED` — 해당 claim의 예상 observable을 실제 실행해 관찰했다.
- `INSPECTED` — diff/file/static state를 직접 관찰했지만 runtime behavior는 실행하지 않았다.
- `UNVERIFIED` — 적합한 check를 실행하지 못했거나 필요한 환경이 없었다.
- `FAILED` — 적합한 check가 실행됐고 예상 observable과 불일치했거나 check가 실패했다.

Content/change/scope claim은 diff/file/static state에 관한 것이므로 `INSPECTED`에 둔다. Passing behavior test는 실행한 runtime behavior만 `VERIFIED`로 만들며, 편집 사실이나 변경 범위까지 `VERIFIED`로 승격하지 않는다.

static inspection만으로 runtime claim을 `VERIFIED`라 하지 않는다. dry-run은 plan만 검증하며 applied state를 검증하지 않는다. 축소·대체 check는 원 claim을 승격하지 않고 실제로 관찰한 더 좁은 claim만 판정한다.

evidence는 claim의 mutation/dependency set에 영향을 주는 마지막 mutation 이후의 parent-session observation이어야 한다. 단 관찰 source가 그 set 밖이고 관찰 뒤 package/version/config/environment 변화가 없으면 세션 내 앞선 직접 관찰을 `INSPECTED` evidence로 재사용할 수 있다. 이 예외로 runtime claim을 `VERIFIED`로 올리지 않는다.

worker summary, 다른 LLM의 판정, 기억, 위치만 적은 citation은 evidence가 아니다. 위임 결과는 부모 세션이 diff와 해당 check를 다시 관찰해야 한다(parent re-observation). external write는 목적지 상태를 read-after-write로 관찰해야 하며 write 요청의 성공 응답만으로 applied state를 주장하지 않는다.

각 evidence entry에는 exact command, 모호할 때 cwd, exit code, 판정에 필요한 verbatim output을 넣는다. 같은 경로 기준으로 diff와 check를 실행하고 불일치가 의심되면 파일을 다시 읽는다. 기존 identifier·path·flag, impact/caller, wiring/entrypoint claim도 실제 정의·사용처·entrypoint 관찰에 연결한다.

## 5. 막혔을 때 — 같은 문을 세 번 두드리지 않는다

동일 에러/증상 2회 실패 = 2-strike — 명령이 달라도 같은 접근이다. 에러가 명시적으로 일시성(timeout·lock·connection reset)을 가리키면 사유 1줄과 함께 1회 추가 재시도만 허용한다.

2-strike 후에는 진단 블록을 실행한다: 에러 원문 인용 + 서로 다른 가설 2개 이상 + 가설을 가를 실험 1개. 실험 출력 원문을 인용하고 어느 가설이 지지/기각됐는지 판정한 뒤에만 다음 수정을 시도할 수 있고, 다음 시도는 살아남은 가설을 명시적으로 인용한다.

그래도 같은 지점이면 외부 시선으로 간다 — fresh-context subagent에 문제 서술과 에러 원문만 주고 새로 보게 하거나, 막힌 지점을 보고하고 /cross-verify를 제안한다(입력 제한·§4 적용은 §6 준용).

## 6. 외부 검증 — 자기 가중치의 맹점 밖으로

아래 신호가 하나라도 있으면 자기검토 뒤 `/cross-verify`를 제안한다. 자동 실행하지 않는다.

- 비가역 작업이 포함된 변경 (마이그레이션, 대량 삭제, force push)
- 보안·비용·PHI를 다루는 코드 경로
- 3개 이상 파일에 걸친 구조 변경
- `FAILED` claim을 고쳤지만 수정의 파급 범위가 확신되지 않을 때

선택 패치(설치 시): 위 신호가 비가역·보안/비용/PHI·3+파일 등으로 무겁게 겹치면 `/cross-verify` 대신 `/deep-verify`를 제안할 수 있다.

무료 대안은 fresh-context verifier다. 원요청, `Qn`/claim/expected observable, scoped diff/status, check 출력만 주고 빌더의 결론은 주지 않는다. verifier 결과에도 §4를 그대로 적용한다. `/cross-verify` 실행 중이면 그 프로토콜이 우선한다.

finding 처리: 재현을 먼저 시도하고, 재현되면 재현 증거를 첨부해 수정 여부를 사용자에게 묻는다. 기각에는 반증 증거(코드 인용 또는 실행 출력)가 필요하다 — "그럴 것 같지 않다"는 기각 사유가 아니다. 정확성·명시 요구와 무관한 개선 제안은 고치지 않고 목록으로 전달한다. /cross-verify 실행 중이면 그 스킬의 합의 루프가 우선한다.

## 7. 경계 — 기존 규범·다른 절차와의 관계

메모리·harness가 이미 커버하는 규범(결정점 사용자 확인, 한국어 산문+영어 코드, 사실/추정 라벨, 잔여물 정리, git 규칙)은 재규정하지 않으며, 실제 충돌 시 그쪽이 우선한다. 우선권 발동에는 충돌하는 양쪽 문장의 인용이 필요하다 — 인용 없는 충돌 주장은 무효다.

분업: design-agent/implement-agent 워크플로우의 자체 게이트·검증 계약이 절차를 지배하고, 이 스킬은 §4 claim-strength 계약만 적용한다. 사용자가 `/verify`, `/code-review`, `/cross-verify`를 명시 호출하면 그 절차가 우선한다.
