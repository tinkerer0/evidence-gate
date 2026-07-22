# evidence-gate

Claude Code(및 Claude Agent SDK) 세션용 품질 게이트 스킬입니다. 파일·상태를 바꾸거나 작업 상태를 주장하는 턴에서 **작업 규모와 변경 귀속을 먼저 고정**하고, 모든 claim을 **claim-specific evidence**에 연결합니다.

핵심 명제는 *"초안은 제출물이 아니라 검토 대상이다"* 이고, 출발점은 *"자기보고는 품질 신호가 아니다"* 입니다 — "확인했습니다"라고 쓰는 비용이 실제 확인 비용보다 훨씬 싸기 때문입니다. 그래서 모든 통과 판정은 진술이 아니라 아티팩트(명령 출력, exit code, diff, 파일:라인)가 내리고, 문장은 그 아티팩트를 인용하는 역할만 합니다.

## 무엇을 하나

흐름 전체를 무겁게 만들지 않고 네 지점을 고정합니다.

- **부하 비례** — 좁은 단일 변경과 주 파일+수집되는 test pair만 LIGHT로 두고, 다파일·public contract·외부 상태·고위험·위임 변경은 FULL로 올립니다.
- **귀속 baseline** — 첫 mutation 전에 scoped `git status --short`를 기록하고, 긴 작업·위임 복귀·compaction 뒤 concurrent change를 재확인합니다.
- **claim-strength contract** — `VERIFIED`, `INSPECTED`, `UNVERIFIED`, `FAILED`만 사용하며 evidence strength가 claim strength의 상한입니다. static inspection과 dry-run은 runtime/applied-state claim을 `VERIFIED`로 만들지 못합니다.
- **짧은 감사 가능 보고** — `Changed`, `Claims`, `Evidence`, `Unverified/failed`를 공통으로 쓰고 FULL에서는 `Coverage: Q1→C1/E1`과 `cross-verify:`를 추가합니다. report final은 canonical block에서 조립해 `Changed:`를 첫 token과 첫 non-whitespace line으로 고정하고, 필요한 optional `Scale:`은 그 바로 뒤에 한 번만 둡니다. baseline-dirty attribution은 해당 `INSPECTED` scope claim에만 두며 block 앞뒤에는 prose를 두지 않습니다.

자세한 절차와 report shape는 [`SKILL.md`](SKILL.md)에 있습니다.

**Status:** Claude Code 스킬 문서·절차 · `Last reviewed: 2026-07-22` against default-branch source.

## 선택적 연동 (optional integrations)

이 스킬은 **단독으로 동작**합니다. `/cross-verify`, `/deep-verify`, `/verify`, `/code-review`, `design-agent` 참조는 같은 환경에 있을 때만 쓰는 선택적 연동 지점입니다. 없어도 규모 판정, 귀속 baseline, claim-evidence 계약은 그대로 동작합니다. 일부 형제 스킬은 공개 저장소가 아닐 수 있어 링크나 내부 설명을 추가하지 않습니다.

## 트리거 스모크 · 최소 출력 예

`SKILL.md` frontmatter `description` 기준, 아래 같은 턴에서 게이트가 로드되는 것을 기대합니다(이 refresh에서 런타임을 실행하지 않음 — **미실행 안내**).

| 입력(의도) 예 | 기대 동작(문서 기준) |
|---|---|
| 파일 1개를 고치거나 새로 쓰는 턴 | 규모 판정 → 대개 `scale: LIGHT` 선언 후 claim-linked 보고 |
| `ㅇㅋ` / `진행해` 로 계획된 변경 승인 | 승인 턴도 게이트 대상(본문 description) |
| `계속` / resume 으로 작업 재개 | 재개·상태 주장 턴도 게이트 대상 |
| 조회만 하는 질문(파일·상태 변경 없음) | 규모 판정 생략(면제) — 단 §4 어휘 규칙은 유지 |

**LIGHT canonical example** (placeholder-only; optional `Scale:` 위치 포함; 마지막 표시 줄에서 응답 종료):

```
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

**FULL output shape** (placeholder-only; optional `Scale:` 위치 포함; 마지막 표시 줄에서 응답 종료):

```
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

## 설치

Claude Code 스킬이므로 `SKILL.md`를 스킬 디렉토리에 두면 됩니다:

```
~/.claude/skills/evidence-gate/SKILL.md
```

`SKILL.md`의 `description` frontmatter가 트리거를 정의합니다. 파일 변경·상태 명령·완료 보고 턴에 더 확실히 로드되게 하려면, 사용 중인 `CLAUDE.md`에 트리거 한 줄을 함께 두는 방식이 잘 맞습니다.

## 피드백

제가 이런 분야를 접한 지 얼마 안 돼서 부족한 점이 많습니다. 고칠 점이나 알려주실 내용이 있다면 issue나 PR로 남겨주시면 너무 감사하겠습니다.

## License

MIT — [LICENSE](LICENSE) 참고.
