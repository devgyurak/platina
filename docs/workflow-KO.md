<!-- i18n: source=docs/workflow.md source-sha256=1b29bc76efca translation-sha256=b04e4ad0fc76 -->
# 에이전트 개발 워크플로

원문(영어): [workflow.md](workflow.md)

이 저장소는 코딩 에이전트(Claude Code, Codex, Pi를 똑같이 지원)가 개발하고 사람 메인테이너가
결정을 승인하는 방식으로 만들어졌다. 이 문서는 그 구성 요소들이 어떻게 맞물리는지 설명한다.

## 1. 원본 하나, 에이전트 셋

```
.agents/                      도구 중립적인 원본 (여기를 고친다)
├── rules/*.md                경로별 규칙
├── agents/*.md               서브에이전트 정의
└── skills/*/SKILL.md         워크플로 (Agent Skills 표준)
        │
        │  make agents-sync  (tools/agentsync.py; 어긋나면 CI 실패)
        ▼
.claude/rules, .claude/agents, .claude/skills      Claude Code
.codex/agents/*.toml                               Codex   (스킬은 .agents/skills에서 읽음)
.pi/agents/*.md                                    Pi      (스킬은 .agents/skills에서 읽음)
AGENTS.md 인덱스 블록                               Codex, Pi (Claude는 CLAUDE.md를 거쳐)
```

| 기능 | Claude Code | Codex | Pi |
|---|---|---|---|
| 프로젝트 지침 | `CLAUDE.md` -> `@AGENTS.md` | `AGENTS.md` | `AGENTS.md` |
| 규칙 | `.claude/rules/` (자동, 경로별) | `AGENTS.md`의 규칙 인덱스 | `AGENTS.md`의 규칙 인덱스 |
| 스킬 | `.claude/skills/` | `.agents/skills/` | `.agents/skills/` |
| 서브에이전트 | `.claude/agents/` (Agent 도구) | `.codex/agents/*.toml` (에이전트 역할) | `.pi/extensions/subagent`를 통한 `.pi/agents/` (`agentScope: "project"`) |
| 편집 훅 | `.claude/settings.json` | `.codex/hooks.json` | `.pi/extensions/platina-guard.ts` |

세 편집 훅은 모두 같은 스크립트 `tools/hooks/agent_hook.py`를 부른다.
- **pre**: 생성된 파일의 편집을 막는다(`.agents/`를 고쳐야 한다).
- **post**: 편집한 파일에 `tools/guards`와 `ruff check`를 돌려 위반 사항을 에이전트에게 바로
  돌려준다.

## 2. 기능 루프

모든 변경은 `feature-loop` 스킬을 따른다.

```
 frame ──► open facts ──► design check ──► red tests ──► implement ──► refactor
 (issue,    (run-spike,     (architect;      (test-writer)  (hook feedback
  design     pg-researcher,  ADR if needed)                  on every edit)
  section)   type-reviewer)                                         │
                                                                    │
   close ◄──────────────── review-change ◄──────────────────────────┘
 (docs-sync: design + KO,  (arch-guardian + code-reviewer + test-reviewer
  architecture, CHANGELOG)  + type-reviewer, in parallel)
```

게이트: 가드 통과 -> 테스트가 올바른 이유로 실패 -> `make check`(DB가 관련되면 `make test-int`
포함) 통과 -> 열린 BLOCKER/MAJOR 리뷰 지적 없음 -> `make check-all`.

**코드보다 사실이 먼저.** 설계에는 실험으로만 답이 나오는 열린 질문이 남아 있다(설계 §9:
pyright·mypy에서의 타입 표면, SSI 거짓 충돌, Alembic 왕복, 유스케이스 10개를 종이에 옮기기).
`run-spike` 스킬은 각 질문을 `spikes/` 아래의 버리는 코드와 `docs/spikes/` 아래의 남는 기록으로
바꾸고, 설계 체크리스트에 표시한 뒤, 결론이 결정을 바꾸면 설계를 고치거나 ADR을 쓴다.

문서는 코드와 함께 움직인다. `docs-sync` 규칙이 변경 종류마다 같은 변경 안에서 고쳐야 할
문서를 정해 두었고, `arch-guardian`은 빠뜨린 것을 MAJOR로 보고한다.

작업은 GitHub에서 추적한다. 단계마다 마일스톤 하나(`Phase 0 - Experiments`, `Phase 1 - Core execution path`, `Phase 2 - Event pipeline`, `Later`. 1·2단계 구분은 이슈 #6이
정할 때까지 설계 §9.6의 제안이다), 로드맵 항목마다 설계 절·범위 체크리스트·의존 이슈를 적은
이슈 하나, 라벨은 종류(`feature`, `spike`, `test`, `ci`, `documentation`), 영역(`area:*`),
절차(`needs-decision`, `blocked`)로 단다. PR은 `Closes #N`으로 이슈를 닫는다.

사람이 정하는 것: ADR 수락, 가드·규칙 변경, 단계 범위(설계 §9.6), 릴리스.

**ADR은 가볍다.** 설계 문서가 아직 정하지 않은, 되돌리기 비싼 결정에만 쓴다. 짧게(맥락, 결정,
결과, 검토한 대안) 쓰고, 메인테이너가 읽고 납득하면 수락된다. 리뷰어 판정 필수 조건이나 개정
절차 같은 형식은 없다. 에이전트는 `Proposed`로 쓰고, 메인테이너의 말이 있을 때만 `Accepted`가
된다. 자세한 내용은 `docs-and-adr` 규칙과 `write-adr` 스킬.

브랜치: 작업은 `develop`에서 딴 `<prefix>/<kebab-summary>` 브랜치에서 하고 `develop`으로 PR을
보낸다. `main`은 릴리스 병합만 받는다. GitHub 룰셋이 이를 강제한다. `develop` 병합에는 코드
오너(@devgyurak)의 승인이 필요하고 메인테이너는 PR에서 이를 우회할 수 있다. `main`에는 누구도
푸시할 수 없고, `develop`에서 온 PR만 CI `check` 잡과 free-threaded 잡이 통과했을 때 받는다(`branch-policy.yml`). 릴리스는 `main`의 `vX.Y.Z` 태그다.
CI(`ci.yml`)는 모든 PR과 `develop`·`main` 푸시에서 돈다: 3.14·3.15의 `make check`,
free-threaded 3.14t의 단위 테스트(`make test-unit-ft`), 통합 테스트. 커밋·PR 제목은 접두어 하나를 쓴다:
`ADD:` `FIX:` `REF:` `DEL:` `DOCS:` `UPT:` (`commit` 스킬).

## 3. 서브에이전트

| 에이전트 | 권한 | 루프에서의 역할 |
|---|---|---|
| `architect` | read-only | 설계 검토, 스파이크 결론, ADR 초안 |
| `pg-researcher` | review | 문서와 실험으로 확인한 PostgreSQL / psycopg 사실 |
| `test-writer` | write | red 단계: 명세에서 실패하는 테스트 작성 |
| `arch-guardian` | review | diff의 아키텍처·불변식 리뷰, 문서 어긋남 |
| `code-reviewer` | review | 정확성 리뷰 (엔진, 트랜잭션, SSI, 취소) |
| `test-reviewer` | review | 테스트 규칙과 충분성 |
| `type-reviewer` | review | pyright와 mypy에서의 공개 타입 표면 |
| `translator` | write | `-XX` 번역을 원문과 맞춤 |

`review` 에이전트는 명령(테스트, 타입 체커, DB 실험)을 실행할 수 있지만 저장소 파일은 고치지
않는다.

## 4. 기계적 강제

| 계층 | 도구 | 시점 |
|---|---|---|
| 포맷, 린트 | ruff | 편집 훅, `make lint`, pre-commit, CI |
| 타입 | pyright(`src`는 strict) + mypy `--strict` | `make typecheck`, CI |
| 공개 타입 표면 | `tools/typetests.py` (`# expect-error[<pyright 규칙>, <mypy 코드>]`로 표시한 `tests/typing/pass_*`, `fail_*`를 두 체커로 검사) | `make test-types`, CI |
| 레이어 | import-linter (`exhaustive`: 모든 패키지가 레이어에 있어야 함) | `make guard`, pre-commit, CI |
| 영역(A101-A106: `core`/`sql`은 허용 목록의 표준 라이브러리 모듈만 import, `async` 금지, 별칭을 거쳐도 시계·난수 ID 호출 금지, psycopg는 `drivers`에서만, SQLAlchemy/Alembic은 `migrate`에서만, 껍데기는 asyncio가 아니라 anyio) | `tools/guards` | 편집 훅, `make guard`, pre-commit, CI |
| 테스트 규칙: GWT, 제어 흐름 금지 (T1xx-T3xx) | `tools/guards` | 위와 같음 |
| 언어: 영어 + 번역, 양방향 낡음 감지 (L1xx/L2xx) | `tools/guards` | 위와 같음 |
| `main` / `develop` 푸시 금지 | `tools/hooks/pre_push.py` (git pre-push, `make hooks-install`) | 훅을 설치한 클론의 모든 푸시 |
| 에이전트 설정 어긋남 | `tools/agentsync.py --check` | `make agents-check`, pre-commit, CI |
| DB 의미 | 실제 PostgreSQL 위의 pytest | `make test-int`, CI |
| free-threaded CPython에서의 스레드 안전성: 3.14t에서 단위 테스트를 테스트마다 8개 스레드로 실행(pytest-run-parallel), 실행 전후에 GIL이 켜져 있거나, `thread_unsafe(reason=...)` 없이 한 스레드로 돈 테스트가 있거나, 경고가 기록됐거나, ADR-0002의 카운터 테스트가 통과하지 않았거나, 안전하지 않은 `n += 1` 대조 카운터에서 경합이 보이지 않으면 실패 | `tools/freethreaded.py` | `make test-unit-ft`, CI |
| 브랜치 흐름 | GitHub 룰셋 + `branch-policy.yml` + `CODEOWNERS` | `develop`·`main`으로의 모든 푸시·PR |

가드에는 인라인 예외 처리가 없다. 가드가 아니라 코드를 고치고, 가드 변경은 메인테이너가 정한다.

## 5. 테스트 규칙 한 문단

모든 테스트에는 `# given` / `# when` / `# then` 표시가 있고, `for`, `while`, `if`, `try`,
`match`, 컴프리헨션, 조건식이 없다. 변형은 `pytest.mark.parametrize`나 Hypothesis로 만들고,
보조 로직은 `tests/support/`에 둔다(도구도 쓰는 보조 로직은 `tools/`에 두며, `tools/`는 `tests/`를
import하지 않는다). 코어는 DB 없이 테스트하고(법칙, 모든 yield 지점에 오류를
넣는 엔진 재생, 컴파일러 스냅샷), DB 의미는 실제 PostgreSQL로만 테스트하며 인메모리 가짜 DB는
쓰지 않는다. 공개 타입 표면은 pyright와 mypy 둘 다로 검사한다.

## 6. 언어

코드, 주석, 문서, 에이전트 파일의 원본 언어는 영어다. `docs/i18n.toml`에 적힌 사람용 문서는
`<stem>-<LANG>.md` 이름의 번역을 함께 둔다(예: `README-KO.md`, `docs/design/design-KO.md`).
번역은 원문의 리비전을 고정해 두므로, 영어 원문이 바뀌면 가드가 번역을 오래된 것으로 표시한다.

## 7. 일상 명령

```bash
make hooks-install                # 클론마다 한 번: pre-commit 검사 + pre-push 가드
make check                        # 세션 시작 (DB 불필요)
make db-up && make test-int       # PostgreSQL이 관련될 때
make db-up-durable                # 비율·처리량·지연을 재는 스파이크
make test-types                   # 공개 시그니처를 건드린 뒤
make test-unit-ft                 # free-threaded 3.14t에서 단위 테스트 (별도 .venv-ft)
make agents-sync                  # .agents/를 고친 뒤
uv run python -m tools.guards --changed
```

## 8. GitHub 설정 (메인테이너, 한 번)

**현재 상태(2026-11-25):** 완료. `develop`이 기본 브랜치이고, 룰셋 두 개가 활성 상태이며,
마일스톤·라벨·로드맵 이슈(#1-#67, #47·#53·#56·#62·#66·#67은 풀 리퀘스트)가 있다. 로컬 pre-push 훅(`make hooks-install`)은 두 번째
방어선으로 남는다. 에이전트는 메인테이너가 요청할 때만 GitHub 설정·마일스톤·라벨을 바꾼다.

- [x] `main`에 첫 커밋, 그다음 거기서 `develop` 생성, `develop`을 기본 브랜치로.
- [x] `develop` 룰셋: PR 필수, 코드 오너(`.github/CODEOWNERS`) 승인 1개, 새 푸시 시 기존 승인
      무효, squash 또는 merge commit, 저장소 관리자는 PR에서 우회 가능, force push 금지, 삭제 금지.
- [x] `main` 룰셋: PR 필수, merge commit만, 우회 없음, 필수 상태 검사
      "main accepts PRs from develop only"(`.github/workflows/branch-policy.yml`)와
      "lint, types, guards, unit, type tests (py3.14)" / "(py3.15)", "unit tests, free-threaded (py3.14t)"(`ci.yml`), force push 금지,
      삭제 금지. CI 잡 이름을 바꾸면 룰셋에서도 바꿔야 한다.
- [x] 마일스톤: `Phase 0 - Experiments`, `Phase 1 - Core execution path`, `Phase 2 - Event pipeline`, `Later`.
- [x] 라벨: `feature`, `spike`, `test`, `ci`, `documentation`, `needs-decision`, `blocked`,
      `area:core`, `area:sql`, `area:app`, `area:runners`, `area:drivers`, `area:outbox`,
      `area:migrate`, `area:codegen`, `area:testing`, `area:integrations`, `area:cli`,
      `area:tooling`.
- [x] 로드맵 이슈 #1-#67: 설계 §9 실험, 그리고 설계 §3-11의 모든 패키지·기능을 의존 관계와 함께
      (#1은 이 설정 작업, #48-#52와 #54, #55는 스파이크 0001에서, #57-#61은 스파이크 0002에서, #63은 스파이크 0004에서, #64-#65는 스파이크 0003에서 나옴,
      #47·#53·#56·#62·#66·#67은 풀 리퀘스트).
- [x] 첫 구현 전에 ADR-0001(조립 패키지와 seal)과 ADR-0002(새 ID를 주입된 소스에서 받기) 결정 - 둘 다 수락.

항목을 마치면 같은 변경에서 이 절(과 영어 원문)을 고친다.
