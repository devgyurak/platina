<!-- i18n: source=docs/design/design.md source-sha256=6d2441aaba56 translation-sha256=a47ac8a85c28 -->
# Platina 설계 문서

> **Platina**: 백금(platinum)의 옛 스페인어 이름. 백금이 산에도 녹지 않고 반응하지 않듯, 도메인 코드는 DB와 반응하지 않는다.
> Spring + JPA에서 넘어온 백엔드 개발자의 시선으로, 기존 Python ORM의 불편함에서 출발해 설계 철학을 정리하고, 열린 질문을 조사해 결정까지 내린 문서.
>
> 작성일: 2026-11-24 · 상태: 설계 확정(프로토타입 전) · 개정: 합성 의미론, 내부 아키텍처, 테스트 전략 추가 → 외부 리뷰 5회 반영(호출·쓰기 문법, 의존 로드, 정체성 모델, 실행 ID, 내부 테이블 규칙, 작업 파이프라인, 스키마 도구 혼합안)

---

## 결정 요약

| 영역 | 결정 |
|---|---|
| 형태 | **독립 ORM**(쿼리 컴파일러·실행 엔진 직접 구현). DDL·리플렉션·마이그레이션만 SQLAlchemy Core + Alembic, 선택 extra `platina[migrate]` |
| 이름 | **Platina** (패키지 `platina`, CLI `platina`). PyPI 비어 있음, GitHub에 동명 라이브러리 없음 |
| 라이선스 | **Apache-2.0** |
| Python | **3.14 이상** |
| DB | **PostgreSQL 우선**. MySQL·MariaDB는 지원 계획 있음, 시점 미정 (일부 기능 축소 모드) |
| 드라이버 | **psycopg 3.3 이상** 단일 (sync·async·파이프라인·COPY·t-string) |
| 로드 선언 | `Annotated[Order, Load(...)]` + `type` 별칭. 의존 로드도 선언(`Load.when` 식 / `Load.after` 함수). 제너레이터 없음 → 왕복 단계 수는 seal에서 확정 |
| 검증 시점 | import 시점이 아니라 **seal 시점**(앱 기동 시 `app.seal()`) + CLI `platina check` |
| 기본 격리 수준 | Command는 **SERIALIZABLE + 자동 재시도**(탈출구는 REPEATABLE READ + version), Query는 READ COMMITTED |
| 외부 IO | 유스케이스 안에서는 금지. 외부 IO는 **process 핸들러**에서만 |
| 합성 | 단계는 **`with chain(a, b) as (c, a, b)`**로만. 최신 상태 뷰로 같은 이름 재바인딩, 별칭은 이동 표시로 차단. `+`는 한 단계 안에서만 |
| 호출·쓰기 | `app.run(uc.bind(...), 옵션)`. ref는 타입상 엔티티인 자리표시자(JPA `getReference`, `.set` 불가). 엔티티는 `Entity`를 상속하고, 필드는 `Col[T]`이며 클래스에서는 `Column[Owner, T]`로 읽힌다. 생성은 키워드 생성자 `Order(...)`, 수정은 `.set(Order.status.to(...))`, 임베디드 경로는 `Order.total.path(Money.amount)` |
| 커밋 순서 | FK·유니크 키 의존성 그래프 위상 정렬 + 배치 |
| 왕복 | 로드 배치 1회 + 커밋 배치 1회(쓰기·COMMIT·LSN 조회까지) |
| 실행 ID | 모든 `app.run`에 실행 ID(호출자 멱등 키 또는 자동 uuid7). 조회 없이 INSERT로 선점 → 멱등성과 커밋 결과 판정(재실행)을 하나로 |
| 내부 테이블 규칙 | 추가 전용 내부 테이블(실행 ID, outbox, 작업, 완료 기록)은 SERIALIZABLE 안에서 읽지 않음. INSERT만 |
| 프로젝션 | 기본 **inline**. `into`·`key`를 선언하고 본문은 필드 연산만. inline 키는 엔티티 ID만(날짜·상수 키는 async 또는 사유 opt-in), 재시도율 메트릭 |
| 정체성 | 커밋됐는가 = **실행 ID**, 소비 진행 = **xid**, 복제 = **LSN**, 순서 = **version**. 토큰 = (xid, LSN) |
| outbox·소비 | **추가 전용 이벤트 로그**(xid 워터마크). 프로젝션은 직렬 소비자(체크포인트와 효과를 한 트랜잭션), `then`·`@process`는 2계층 작업 파이프라인(짧은 리스, 유니크 INSERT 펜싱, 집계별 순서, dead-letter). `@process`는 서술을 돌려줌 |
| 마이그레이션 | 엔티티 레지스트리 → SQLAlchemy `MetaData` → Alembic autogenerate (선택 extra). 충실도는 스파이크로 확인 |
| 코드젠 | 임시 DB로 타입 추론, **생성물은 커밋** (CI·배포에 DB 불필요) |
| 비동기 | anyio API로 작성, 백엔드는 asyncio(+uvloop). trio 미지원 |
| free-threaded | 코어는 3.14t CI 대상, 드라이버 공식 지원은 psycopg 휠 출시 후 |
| 코드베이스 | sans-IO 코어(명령을 yield하는 엔진) + 얇은 sync/async 실행기, import-linter로 경계 강제 |
| 테스트 | 코어는 DB 없이(속성 기반·오류 전수 주입), DB 의미는 실제 PostgreSQL로. 인메모리 가짜 DB 없음 |

---

## 0. 배경: 왜 새로 만드는가

### 기존 Python ORM의 공통 문제
- **표준 부재**: JPA 같은 스펙이 없어 ORM마다 의미론이 다름 (영속성 컨텍스트가 있는 ORM / 없는 ORM 혼재)
- **트랜잭션·DI 통합 부재**: `@Transactional` 같은 선언적 경계와 전파 속성이 없음
- **캐시·관측·커넥션 풀·감사·멀티테넌시** 등 주변 생태계가 Java 대비 빈약
- **async 생태계 분열**: SQLAlchemy(greenlet 브릿지), Django(스레드풀 위임), Tortoise(얕은 기능)
- **유지보수 리스크**: 핵심 메인테이너 1인 의존 구조가 많음

### SQLAlchemy에 대한 평가
엔진(unit of work, identity map, 로딩 전략)은 Hibernate급. 다만:
- 위험한 기본값 (`lazy="select"`, `expire_on_commit=True`, autoflush)
- 넓은 API 표면 (Core/ORM, 1.x/2.0 공존)
- 세션·트랜잭션 경계를 사용자에게 떠넘김
- async가 sync 코어 + greenlet 래핑
- 타입 지원이 반쯤, 관계 설정에 문자열이 많음
- Repository·페이지네이션·감사·soft delete 등 배터리 부재
- 원인과 발생 지점이 먼 에러 메시지

### 문제들의 공통 뿌리
N+1, `MissingGreenlet`, expire 사고, 흐릿한 레이어 경계, DB 없이 테스트하기 어려운 도메인 로직은 모두 하나로 귀결된다.

> **도메인 코드가 객체를 통해, 예측할 수 없는 시점에 IO를 한다.**

---

## 1. 철학

> **도메인 코드는 DB가 존재한다는 사실을 몰라야 한다.**
> **ORM은 객체를 관리하는 게 아니라 경계를 관리한다.**

- JPA·SQLAlchemy가 IO를 "투명하게" 만드는 데 집중했다면, Platina은 IO가 일어날 수 있는 장소를 **한 곳으로 모은다.**
- 목표는 "실수하기 어려운 ORM"이 아니라 **"실수할 장소가 없는 ORM"**.
- 결과적으로 **CQRS가 기본 구조인 ORM**이 된다. 읽기와 쓰기가 처음부터 다른 경로이고, 그 사이를 ChangeSet과 이벤트가 잇는다.
- 철학은 타협하지 않되, **철학에 이르는 계단**을 만든다.

### 우선순위
**정확성 > 명시성 > 점진적 편의성 > 성능**

이 우선순위는 실제 결정에 쓰인다. 예: 기본 격리 수준을 SERIALIZABLE로 둔 것(§8.3)은 정확성을 성능보다 앞에 둔 결과다.

---

## 2. 원칙

### 세 기둥
1. **선언된 읽기**: 유스케이스가 필요한 데이터를 시그니처에 선언하고, ORM이 함수 진입 전에 전부 로드한다. 로드 계획은 seal 시점에 확정·검증된다.
2. **순수한 도메인**: 엔티티는 불변 스냅샷이다. 도메인 함수는 스냅샷을 받아 변경 내역을 돌려준다. 함수 안에는 세션도 `await`도 없다.
3. **변경은 데이터**: dirty checking 대신 ChangeSet이 일급 값이다. 들여다보고, 합치고, 직렬화할 수 있다.

### 세부 원칙
- **암묵적 IO 금지**: 속성 접근은 절대 DB를 치지 않는다. 미로드 관계 접근은 즉시 에러.
- **안전한 기본값**: `lazy="raise"`, expire 없음, autoflush 없음, SERIALIZABLE. 위험한 건 opt-in.
- **경계는 라이브러리가 소유**: 세션을 인자로 들고 다니지 않는다. 유스케이스 = 트랜잭션.
- **순수/비순수의 두 종류만 존재**: 유스케이스(순수)와 process 핸들러(외부 IO 허용). 그 중간은 없다.
- **설정으로 의미를 바꾸지 않는다**: 같은 코드가 옵션에 따라 다르게 동작하는 기능은 두지 않는다. 의미가 다르면 이름(문법)을 다르게 한다.
- **방법은 하나만**: 쓰기는 `.set(...)`, 단계 합성은 `chain`, 실행은 `app.run`/`app.query`. 같은 일을 하는 두 번째 문법을 두지 않는다.
- **감지보다 제거**: 실수를 사후에 감지하는 장치를 붙이기보다, 실수가 생길 수 있는 구조를 빼거나 타입 에러로 만든다.
- **SQL은 1급 시민**: ORM은 SQL을 숨기지 않고 쓰기 편하게 만든다.
- **문자열 대신 참조, 런타임 대신 코드젠**.
- **관측 가능성 내장**: 쿼리 수, N+1 의심, OpenTelemetry span이 기본.
- **에러는 원인 지점을 알려준다**.
- **코어는 작게, 배터리는 공식 플러그인으로**.
- **점진적 도입**: 각 단계가 혼자서도 가치를 준다.
- **행 변경과 도메인 이벤트를 구분**: 감사 로그는 diff로, 읽기 모델은 도메인 이벤트로.

### 다른 ORM에서 가져오는 것 / 가져오지 않는 것

| 출처 | 가져옴 | 반면교사 |
|---|---|---|
| JPA / Hibernate | 선언적 트랜잭션, `@Version`, 값 객체, DTO 프로젝션, Statistics, 기동 시 스키마 검증, `getReference`(자리표시자 ref) | 암묵적 lazy proxy, OSIV, detached/merge 상태 기계, 메서드 이름 기반 쿼리 |
| EF Core | `AsNoTracking`(조회 전용 모드), Owned types | |
| Prisma | lazy loading 없음, TypedSQL, shadow DB drift 감지 | 사이드카 쿼리 엔진, 생성 시 DB 연결 강제 |
| TypeORM | Active Record / Data Mapper 병행 | 문자열 기반 relation·QueryBuilder |
| Ecto | 스키마는 순수 데이터 / DB 접근은 Repo만, Changeset, `Ecto.Multi` | |
| jOOQ / Drizzle / sqlc | SQL 친화 DSL, `.sql` → 타입 붙은 함수 코드젠 | |
| Rust | 이동(move): `chain`에 넘긴 원본 참조는 더 쓸 수 없음 | |
| SQLAlchemy | `Mapped[T]` 방식의 디스크립터 어노테이션(`Col[T]`), Core의 DDL·리플렉션과 Alembic(선택 extra) | 기본값·세션 경계 |
| Spring Modulith | 모듈 경계 검증, 모듈 간 이벤트 | |

---

## 3. 기능

### 3.1 Command (쓰기) 경로
- `@usecase`: 트랜잭션 시작 → 로드 계획 실행 → 순수 함수 → ChangeSet 커밋. 로드부터 커밋까지 한 트랜잭션이며, 사이에 외부 IO가 없어 트랜잭션이 짧다.
- **로드 계획**: `Annotated` 시그니처 선언 기반, seal 시점에 확정·검증. 선언했지만 안 쓴 관계 경고
- **의존 로드**: `Load.when`(컬럼 식, 서브쿼리로 접혀 추가 왕복 없음) / `Load.after`(타입 단 순수 함수, 로드 단계 1개 추가). 함수가 ref 목록을 돌려주면 한 번에 배치 로드. 제너레이터는 없고, 왕복 단계 수는 seal에서 확정
- **호출**: `app.run(uc.bind(...))`. `bind`는 유스케이스와 시그니처가 같아 ParamSpec만으로 타입 검사
- **재귀 로드**: `Load.recursive(...)` → `WITH RECURSIVE` (깊이 제한 필수, 순환 감지)
- **ChangeSet**: 행 단위 변경 / 조건 기반 변경 / 청크 스트림이 모두 같은 타입
- **동시성 제어**: 기본 SERIALIZABLE + 자동 재시도. `version`은 요청 사이 낙관적 락(`expected_version`), 이벤트 순서, 유스케이스 안 겹침 감지, 다른 ORM 공존에 쓴다. `owned` 자식의 변경은 루트 버전을 올린다
- **실행 ID**: 모든 실행에 ID를 붙여 조회 없이 INSERT로 선점한다. 같은 키의 재요청은 저장된 결과를, COMMIT 중 연결 끊김·페일오버는 같은 ID 재실행으로 처리한다
- **왕복 2회**: 로드 배치 1회 + 커밋 배치 1회(`Load.after`가 있을 때만 로드 단계 추가)
- **비관적 락**: 핫 로우용 `Load(..., lock=FOR_UPDATE)`
- **outbox**: `emit()`한 도메인 이벤트를 같은 트랜잭션에 INSERT. 이벤트는 `@event(aggregate=...)`만 선언하고 순서 번호는 엔진이 채운다
- **재시도**: 순수 함수라 전체 재실행이 안전. 이벤트는 커밋 때만 기록되므로 중복 발행 없음

### 3.2 대량 쓰기

| 종류 | 로드 | 도메인 규칙 | 컴파일 결과 |
|---|---|---|---|
| 대량 삽입 | 없음 | 생성 시점 검증 | `COPY` / multi-row `INSERT`, FK 순서 자동 정렬, 청크 스트리밍 |
| 집합 기반 갱신 | 없음 | SQL 조건식 | `UPDATE … RETURNING` + outbox CTE, `version` 증가 |
| 청크 갱신 | 청크 단위 | Python 순수 함수 | `unnest` 기반 `UPDATE`, 청크 커밋, 충돌 행 식별 |

- `COPY`는 파이프라인 모드에서 쓸 수 없으므로 대량 삽입 경로는 파이프라인 밖에서 실행한다.
- 집합 기반 갱신이 `@invariant`로 보호된 필드를 건드리면 seal 시점에 거부한다 (§8.2).

### 3.3 Query (읽기) 경로
- TypedSQL: `.sql` 파일 → 코드젠 → 타입 붙은 함수
- t-string 즉석 쿼리: `t"SELECT … WHERE id = {x}"` → DTO 매핑 (컬럼 런타임 검증)
- 추적 없는 조회 전용 모드, READ COMMITTED (레플리카 라우팅 가능)
- 결과는 읽기 전용 Row / DTO. `.set()` 가능한 `Snapshot`은 유스케이스 로드로만 획득 → **CQRS를 타입으로 강제**

### 3.4 CQRS / 프로젝션
- `@projection(on=Event, into=Target, key=Event.field, mode="inline" | "async")`, **기본값 inline**. 본문은 대상 행에 대한 필드 연산만 돌려준다
- inline 프로젝션의 키는 이벤트의 엔티티 ID 필드여야 한다. 날짜·상수 같은 파생 키는 핫 로우를 만들므로 async로 돌리거나 `allow_hot_key="사유"`로 명시한다. 엔티티 ID도 뜨거울 수 있어 프로젝션별 재시도율을 항상 메트릭으로 낸다
- **일관성 토큰**: 커밋 결과에 불투명 토큰(커밋 직후 WAL 삽입 위치 + 트랜잭션 xid)을 담아 반환. 조회 측이 `after=token`으로 넘기면 레플리카가 그 위치까지 따라왔을 때만 레플리카를, 아니면 프라이머리를 사용. async 프로젝션을 읽을 때는 해당 소비자의 워터마크가 그 xid를 지났는지로 판단
- **async 프로젝션의 멱등성**: 소비자 체크포인트를 프로젝션 변경과 같은 REPEATABLE READ 트랜잭션에 기록하므로, `total = total + amount` 같은 멱등하지 않은 갱신도 정확히 한 번 반영된다. 독성 메시지는 건너뛰지 않고 멈추고 알린다
- 처음엔 같은 테이블을 읽는 논리적 CQRS로 시작하고, 필요한 화면에만 별도 읽기 모델

### 3.5 process 핸들러 (외부 세계와의 경계)
- `@process(on=PaymentRequested)`: 외부 IO가 허용되는 유일한 장소. 결과에 따라 실행할 유스케이스의 **서술을 돌려주고**, 디스패처가 그것을 작업 완료 기록과 한 트랜잭션에 커밋한다. 외부 호출에는 프레임워크가 주는 이벤트 기반 멱등 키를 쓴다
- `then`과 `@process`는 2계층 작업 파이프라인으로 처리한다: 짧은 리스, 유니크 INSERT 펜싱, 집계별 순서, 실패 종류별 처리와 dead-letter(§4.10)
- 결제 승인처럼 "외부 결과가 쓰기를 결정하는" 흐름은 `usecase → 이벤트 → process → usecase`로 표현
- 타임아웃·보상 트랜잭션 헬퍼는 공식 플러그인(`platina-saga`)으로

### 3.6 모듈러 모놀리스 지원
- 패키지 단위 `Module("billing", exposes=[...])` 선언
- **다른 모듈의 엔티티는 로드 선언에 넣을 수 없음** (seal 시점 검증)
- `platina contracts`로 import-linter 독립성 계약 설정을 생성해 import 수준에서도 경계를 강제
- 모듈 간 통신은 이벤트 또는 공개 조회 경로로만

### 3.7 운영·개발 도구
- 작업 단위당 쿼리·왕복 수 계측, 같은 모양 쿼리 반복 시 개발 환경 경고 / 테스트 환경 예외
- OpenTelemetry span·메트릭 기본 제공
- 개발 모드: 엔티티 로드 위치·작업 단위 종료 위치 기록
- CLI: `platina check` / `platina gen` / `platina migrate` / `platina pull` / `platina contracts`

### 3.8 공식 플러그인 (코어 밖)
soft delete, 감사, 멀티테넌시, 페이지네이션, Pydantic DTO 생성, saga 헬퍼

---

## 4. 문법

> 아래 코드는 설계안이다. 이름과 시그니처는 프로토타입에서 바뀔 수 있다. §4.2-§4.6의 타입 표면과 §11.8의 오용 목록은 타입 스텁 스파이크([스파이크 0001](../spikes/0001-type-surface.md), ADR-0003, ADR-0004)로 pyright와 mypy에서 확인했다. 나머지 절은 아직 타입 스파이크로 검사하지 않았고, §4.7의 두 줄은 열린 결정에 달려 있다(해당 위치에 표시).
> 예제 도메인: 쇼핑몰의 `billing` 모듈 (주문, 주문 항목, 지갑).

### 4.0 개념 한눈에

| 개념 | 정체 | 누가 실행하나 |
|---|---|---|
| 엔티티 스냅샷 | 한 시점의 행을 담은 불변 객체 | — |
| ref (`Order.ref(id)`, `orders.by_number(n)`) | 타입상 엔티티로 보이는 **자리표시자**. "이걸 로드해 달라"는 뜻 (JPA `getReference`에 해당) | 실행기가 로드해서 스냅샷으로 바꿈 |
| `Changes` | 변경의 서술 (값) | 실행기가 커밋 |
| `@usecase` | 스냅샷을 받아 `Changes`를 돌려주는 순수 함수 + 로드 선언 | `app.run(uc.bind(...))` |
| `@step` | 로드 선언 없는 합성 전용 순수 함수 | `chain` 안에서만 |
| Repository | 찾는 법·로드 프로필·조회·집합 변경의 **서술**만 담음 | `app`이 실행 |
| 실행 ID | 모든 `app.run`에 붙는 ID. 호출자가 준 멱등 키, 없으면 자동 uuid7 | 실행기가 멱등성·커밋 결과 판정에 사용 |
| 작업(job) | 이벤트를 `then`·`@process` 핸들러별로 나눈 처리 단위 | 워커 + 디스패처 |

모든 것이 "서술"이고 실행은 `app` 한 곳에서만 일어난다. `@process` 핸들러조차 유스케이스를 직접 실행하지 않고 서술을 돌려준다(§4.10).

### 4.1 앱 구성

```python
# shop/app.py
from platina import App, Pool, TxDefaults, Retry, SERIALIZABLE

app = App(
    dsn="postgresql://app@primary/shop",
    replicas=["postgresql://app@replica-1/shop"],   # Query 경로 + 일관성 토큰 라우팅
    pool=Pool(min_size=2, max_size=20),
    modules=["shop.billing", "shop.catalog"],       # 모듈 단위로 엔티티·Repository·usecase 수집
    defaults=TxDefaults(
        isolation=SERIALIZABLE,
        retry=Retry(max_attempts=4, base_ms=10, cap_ms=200),
        statement_timeout="5s",
    ),
)

app.seal()   # 로드 계획·모듈 경계·불변식·프로젝션 키·DTO 매핑·집계 선언을 전부 검증. 실패하면 기동 중단
```

- `App`은 설정과 레지스트리일 뿐이고, 커넥션은 `run`/`query` 호출 안에서만 잡힌다.
- 같은 `App`이 async(`await app.run(...)`)와 sync(`app.run_sync(...)`) API를 모두 제공한다. 둘은 같은 엔진을 돌리는 별도 실행기다.

### 4.2 엔티티, 값 객체, 이벤트

```python
# shop/billing/entities.py
from decimal import Decimal
from datetime import datetime
from platina import (
    Entity, value, event, Col, Id, Rel, pk, column, embedded, fk,
    many_to_one, one_to_many, version_column, invariant, Check, Index, server_now,
)

@value
class Money:
    amount: Col[Decimal]
    currency: Col[str] = column(default="KRW")

class Order(Entity, table="orders", aggregate_root=True):
    id: Col[Id[Order]] = pk(generated="uuid7")          # 기본값: 클라이언트에서 UUIDv7 생성
    number: Col[str] = column(unique=True, length=20)
    status: Col[OrderStatus] = column(default=OrderStatus.PENDING, enum_as="text")
    paid_with: Col[PaymentMethod | None] = column(default=None)
    paid_at: Col[datetime | None] = column(default=None)
    total: Col[Money] = embedded(prefix="total_")        # total_amount, total_currency 컬럼
    user_id: Col[Id[User]] = fk(lambda: User)
    user: Rel[User] = many_to_one(via=lambda: Order.user_id)
    items: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=True,
                                         order_by=lambda: Item.position)
    version: Col[int] = version_column()
    created_at: Col[datetime] = column(server_default=server_now())

    class Meta:
        indexes = (Index(lambda: (Order.user_id, Order.created_at.desc())),)
        checks = (Check(lambda: Order.total.path(Money.amount) >= Decimal(0)),)   # DB CHECK 제약으로 생성

    @invariant(fields=lambda: (Order.status, Order.total))  # Python에서만 검증하는 불변식
    def paid_requires_total(self) -> bool:
        return self.status is not OrderStatus.PAID or self.total.amount > 0

@event(aggregate=lambda: OrderPaid.order_id)               # 어느 집계의 이벤트인지만 선언
class OrderPaid:
    order_id: Col[Id[Order]]
    user_id: Col[Id[User]]
    total: Col[Money]
    paid_at: Col[datetime]
    # 순서 번호(집계 버전, 트랜잭션 안 순번)는 엔진이 커밋 때 채운다. 손으로 쓰지 않는다.
```

- **엔티티는 `Entity`를 상속하고**, 테이블 옵션은 클래스 키워드로 넘긴다(ADR-0003). 클래스 데코레이터는 타입 체커가 생성자를 합성하게 할 수는 있지만 멤버를 추가하지는 못한다. 그래서 `Order.ref`, `Order.where`, `Order.stub`, `order.set`에는 기반 클래스가 필요하다(스파이크 0001).
- **모든 필드는 `Col[T]`로 선언한다.** 평범한 어노테이션(`status: OrderStatus = column(...)`)으로는 타입 체커가 클래스 접근(`Order.status`)도 `OrderStatus`로 본다. 클래스에서는 `Column[Order, OrderStatus]`(컬럼이 자신을 선언한 클래스를 안다), 인스턴스에서는 `OrderStatus`로 보이려면 어노테이션 자체가 디스크립터 타입이어야 한다. SQLAlchemy 2.0이 `Mapped[T]`를 쓰는 이유와 같다. 이벤트 필드와 값 객체 필드도 마찬가지다(프로젝션 키의 `OrderPaid.user_id`, 임베디드 경로의 `Money.amount`, ADR-0004).
- **스냅샷은 불변이다.** `order.status = PAID`는 에러이고, 쓰기는 오직 `.set(...)`으로 한다(§4.4). 컬렉션 필드는 인스턴스에서 읽기 전용 `Sequence[Item]`이다.
- **생성은 키워드 생성자다**: `Order(number="A-1", total=..., user_id=...)`. 이벤트, 값과 같다. 필수 필드 누락은 두 체커 모두에서 타입 에러이고, 생성되는 키, `version_column()`, 서버 기본값, 관계는 파라미터가 아니다(§8.2 "생성 문법", ADR-0003).
- **동등성**: 두 스냅샷은 같은 값(컬럼과 로드된 관계, 무엇이 로드됐는지까지 포함)을 가지면 같고, 해시는 엔티티 타입과 기본 키다. ref에 대한 `==`와 `hash()`는 `UnloadedReference`를 낸다(ADR-0003).
- **`owned=True`**: 집계에 속한 자식이다. 자식이 바뀌면 루트의 `version`도 함께 오른다(JPA `OPTIMISTIC_FORCE_INCREMENT`). 그래서 편집 화면이 주문과 항목을 같이 다룰 때 항목만 바뀐 경우도 요청 사이 낙관적 락(§4.6)에 걸린다. 일반 FK 자식(예: 게시글의 댓글)은 `owned`가 아니라 루트를 건드리지 않는다.
- **클라이언트 생성 ID가 기본값이다.** Python 3.14의 `uuid.uuid7()` 덕분에 순수 함수 안에서 새 엔티티의 ID를 안다. `generated="identity"`도 지원하지만, 그 경우 ID는 커밋 결과(`result.created(Order)`)로만 얻는다. 코어는 `uuid7()`을 직접 부르지 않는다. `Order(...)`는 엔진이 호출마다 설치한 소스에서 ID를 받고, 테스트의 직접 호출과 `Order.stub()`은 결정적인 대체 시퀀스를 쓰며, 유스케이스나 step 밖에서 부른 `Order(...)`는 `UsageError`다(ADR-0002).
- 다른 클래스를 참조하는 곳은 `lambda`로 늦게 평가한다. 문자열 참조는 쓰지 않는다.
- 테스트용 인스턴스는 `Order.stub(...)`.

### 4.3 Repository: 찾는 법, 로드 프로필, 조회, 집합 변경

**Repository도 IO를 하지 않는다.** 쿼리와 변경을 서술할 뿐이고, 실행은 `app`이 한다.

```python
# shop/billing/repos.py
from platina import Repository, Profile, Finder, query, dto, select, Select, count, Changes

@dto
class OrderSummary:
    id: Id[Order]
    number: str
    total: Decimal
    item_count: int

class OrderRepo(Repository[Order]):
    # 1) 찾는 법: 호출하면 타입이 붙은 ref(자리표시자)를 돌려준다
    by_number = Finder(Order.number)            # orders.by_number("A-1") -> Order (Finder[Order, str])

    # 2) 로드 프로필: 이름 붙은 EntityGraph
    payable = Profile(Order.items, Order.user)
    with_item_count = Profile(Order.items.count())
    for_update = Profile(Order.items, lock="for_update")   # 핫 로우용 비관적 락

    # 3) 조회: Query 경로 전용, 결과는 DTO (읽기 전용)
    @query
    def summaries(self, user_id: Id[User], limit: int = 20) -> Select[OrderSummary]:
        return (
            select(OrderSummary,
                   id=Order.id, number=Order.number,
                   total=Order.total.path(Money.amount), item_count=count(Item.id))
            .join(Order.items, outer=True)
            .where(Order.user_id == user_id)
            .group_by(Order.id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )

    # 4) 집합 변경 팩토리: 순수 함수, Changes를 돌려줄 뿐
    def expire_older_than(self, cutoff: datetime) -> Changes:
        return (
            Order.where(Order.status == OrderStatus.PENDING, Order.created_at < cutoff)
                 .set(Order.status.to(OrderStatus.EXPIRED))
                 .emit_each(OrderExpired, order_id=Order.id)   # 이벤트 순서 번호는 RETURNING으로 채움
        )

class WalletRepo(Repository[Wallet]):
    by_user = Finder(Wallet.user_id)            # wallets.by_user(uid) -> Wallet

orders, wallets = OrderRepo(), WalletRepo()
```

- **ref는 자리표시자다.** `Order.ref(id)`와 `orders.by_number("A-1")`는 타입상 `Order`지만, 실제로는 "이 행을 로드해 달라"는 표시다. 호출 측에서 ref의 필드를 읽거나 **ref에 `.set`을 하면** 즉시 `UnloadedReference` 에러다. `.set`을 막는 이유는, 로드와 `@invariant` 검사를 건너뛰는 쓰기가 되기 때문이다. 로드 없이 쓰고 싶으면 `Order.where(Order.id == x).set(...)` 집합 변경으로 명시한다(seal에서 불변식 검사를 받는다).
- **요청 사이 낙관적 락**: `Order.ref(id, expected_version=v)`로 넘기면, 로드한 버전이 다를 때 `VersionMismatch`다. 편집 화면을 열 때 받은 버전을 저장 요청에 실어 보내는 패턴(HTTP `If-Match`)이다.
- Finder 인자는 컬럼 타입으로 검사된다. 키워드 문자열이 없다. `Repository[Order]`의 Finder는 `Order`의 컬럼으로 만들어야 하고, 다른 엔티티의 컬럼은 타입 에러다(ADR-0004).
- **쿼리는 자신이 select하거나 join한 엔티티만 참조할 수 있다.** 그 밖의 엔티티 컬럼은 쿼리 서술을 만들 때 거부된다. 이는 타입으로 검사하지 않는다. 여러 엔티티의 컬럼을 받는 호출에서 pyright와 mypy가 소유자를 다르게 추론하기 때문이다(ADR-0004). seal에서도 잡을 수 있는지는 열린 질문이다(#52).
- **Repository는 선택이다.** 처음엔 유스케이스 시그니처에 `Load(...)`를 직접 쓰다가, 같은 로드가 반복되면 `Profile`로 옮긴다.
- **모듈 경계**: Repository는 자기 모듈의 엔티티만 다룬다. `Module("billing", exposes=[orders.summaries])`로 공개한 조회만 다른 모듈에서 쓸 수 있다.

### 4.4 쓰기 문법: `.set(...)` 하나

| 연산 | 의미 | 생성 SQL |
|---|---|---|
| `Order.status.to(v)` | 값 대입 (`v`는 `Column[Order, T]`의 `T`로 검사) | `SET status = $1` |
| `Wallet.balance.path(Money.amount).add(n)` | 임베디드 값 일부의 DB 쪽 증감 (현재 값을 읽지 않음) | `SET balance_amount = balance_amount + $1` |
| `Order.items.add(item)` | 자식 행 추가 | `INSERT` (+ `owned`면 루트 version 증가) |
| `Order.items.remove(item)` | 자식 행 삭제 | `DELETE` (+ 루트 version 증가) |
| `Order.items.update(item, Item.price.to(p))` | 자식 행 갱신 | `UPDATE` (+ 루트 version 증가) |

```python
order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))   # 행 하나
Order.where(...).set(Order.status.to(OrderStatus.EXPIRED))             # 집합 변경, 같은 문법
```

- 필드 이름은 속성 참조라 오타가 타입 에러가 되고, 값 타입도 검사된다. 연산은 자신이 속한 엔티티도 함께 지닌다. `order.set(Wallet.balance.to(m))`, `Order.where(...)` 안의 다른 엔티티 연산이나 `Order.items.update(item, ...)` 안의 다른 엔티티 연산, 잘못된 타입의 자식은 타입 에러다(ADR-0004).
- 한 단계 안에서는 `+`로 변경을 모은다: `order.set(...) + wallet.set(...) + emit(...)`. 한 함수는 하나의 스냅샷만 보므로 오래된 값을 읽을 여지가 없다. 같은 필드를 두 번 쓰면 `ConflictingWrites`다.
- **임베디드 경로**는 `Order.total.path(Money.amount)`(`Column[Order, Decimal]`)로 쓴다. 다른 클래스의 필드를 넘기면 타입 에러다. 값 객체의 일부는 경로를 통해 증감하고(`Wallet.balance.path(Money.amount).add(n)`), 값 전체는 `Order.total.to(Money(...))`로 쓴다. `Order.total.amount`는 제네릭 컬럼으로 타입을 붙일 수 없고, 값 객체에 두 번째 증감 문법을 두는 안은 기각했다(ADR-0004).

### 4.5 유스케이스: 시그니처와 호출

```python
# shop/billing/usecases.py
from typing import Annotated
from platina import usecase, step, Load, Now, INJECTED, Changes, emit

type PayableOrder = Annotated[Order, orders.payable]          # Repository 프로필 재사용
type ChargeableWallet = Annotated[Wallet, Load()]             # 루트만 로드

@usecase
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    if wallet.balance < order.total:
        raise InsufficientBalance(wallet.id)
    return (
        order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))
        + wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))
        + emit(OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=now))
    )
```

**호출: 서술(`bind`)과 실행(`app.run`)을 나눈다**

```python
result = await app.run(
    pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(user.id)),
    idempotency_key=request_id,        # 실행 옵션은 bind가 아니라 run에. 없으면 자동 uuid7
)
result.run_id           # 실행 ID
result.token            # 일관성 토큰 (xid, LSN)
result.created(Order)   # identity PK일 때 생성된 ID
result.events           # 커밋된 도메인 이벤트
result.value            # Changes.returning(v)로 돌려준 값
```

- **타입 검사가 ParamSpec만으로 된다.** `Usecase[P]`의 `bind(*args: P.args, **kwargs: P.kwargs)`는 `pay`와 시그니처가 같다. ref가 타입상 엔티티이고, 실행기가 넣어 주는 파라미터(`Now`, `Actor`, `RequestId`)는 기본값 `INJECTED`를 가지므로 생략할 수 있다. `INJECTED`는 어떤 파라미터의 기본값으로도 받아들여지므로, 잘못 놓인 `INJECTED` 기본값과 `bind`에 넘긴 주입 파라미터에 대한 규칙은 미결이다(#48).
- 실행 옵션(`idempotency_key`, `after`, `timeout`)은 `app.run`의 키워드라 `bind`의 시그니처와 섞이지 않는다.
- 주입값은 시도(attempt)마다 새로 넣는다. 재시도하면 `Now`도 갱신된다.
- 호출자가 멱등 키를 준 실행에서는 `Changes.returning(v)`의 값이 저장되므로 직렬화 가능해야 한다. 자동 ID 실행은 값을 저장하지 않으므로 이 조건이 없다.

### 4.6 트랜잭션 관리

**원칙: `app.run()` 한 번 = 트랜잭션 하나.** 유스케이스 안에는 트랜잭션 API가 없다.

#### 옵션

```python
@usecase(
    isolation=SERIALIZABLE,          # 기본값. 탈출구는 REPEATABLE_READ (아래 참조)
    retry=Retry(max_attempts=4, on_unique=False),
    timeout="2s",                    # SET LOCAL statement_timeout
)
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes: ...
```

- **탈출구는 READ COMMITTED가 아니라 REPEATABLE READ + `version`이다.** READ COMMITTED에서는 로드 계획의 문장마다 스냅샷이 달라 "로드한 스냅샷은 한 시점의 모습"이라는 전제가 깨진다. REPEATABLE READ는 한 스냅샷을 보장하지만 **write skew는 막지 못한다.**

#### 실행 순서: 왕복 2회

```
attempt 1..N:
  [왕복 1] BEGIN ISOLATION LEVEL SERIALIZABLE; SET LOCAL statement_timeout = '2s'
           INSERT INTO run_claim(id) VALUES ($run_id)      ← 실행 ID 선점. 조회 없이 INSERT
           로드 계획 1단계
  (Load.after가 있으면 [왕복 1+k] 로드 단계 k — 단계 수는 seal에서 확정)
  usecase 실행 (순수 함수)        ← 도메인 예외 → ROLLBACK, 그대로 전파
  [왕복 2] 행 변경(FK·유니크 의존성 순) → inline 프로젝션 → outbox
           → INSERT INTO run_result(...)                   ← 호출자 키일 때만
           → SELECT pg_current_xact_id() → COMMIT → SELECT pg_current_wal_insert_lsn()
           ← 40001/40P01 → ROLLBACK, 백오프 후 다음 attempt
```

- 쓰기·COMMIT·LSN 조회를 한 배치로 보낸다. 파이프라인에서 앞 문장이 실패하면 뒤 문장은 실행되지 않으므로 안전하다. 대가로 커밋 결과를 모르는 구간이 넓어지는데, 이는 실행 ID가 덮는다(아래).
- 취소를 막는 shield는 왕복 2 전체에 걸린다.

#### 실행 ID: 멱등성과 커밋 결과 판정을 하나로

모든 `app.run`은 실행 ID를 가진다(호출자의 `idempotency_key`, 없으면 자동 uuid7). 첫 문장에서 `run_claim`에 INSERT하고, 호출자 키인 경우 결과를 `run_result`에 INSERT한다.

| 상황 | 처리 |
|---|---|
| 같은 키로 다시 호출 (재요청, 더블 클릭) | `run_claim` INSERT가 23505 → 롤백 → 별도 READ COMMITTED 트랜잭션에서 `run_result`를 읽어 저장된 결과 반환 |
| 같은 키가 지금 실행 중 | `run_claim` INSERT가 유니크 키에서 대기 → 상대가 결정되면 위 두 경우 중 하나 |
| COMMIT 도중 연결 끊김, 페일오버 | **같은 실행 ID로 다시 실행**. 이미 커밋됐으면 23505(호출자 키면 저장된 결과, 자동 ID면 실행기가 메모리의 결과를 반환), 롤백·유실됐으면 그냥 실행됨 |

- **INSERT를 먼저, 조회 없이** 하는 이유가 둘 있다. ① 호출자 키의 중복 확인은 업무 로직보다 앞에 있어야 한다. 더블 클릭의 두 번째 요청이 유스케이스를 먼저 실행하면, 이미 PAID인 주문을 보고 `AlreadyPaid`를 내버린다. ② "조회해서 없으면 INSERT"는 SERIALIZABLE에서 거짓 충돌을 만든다(아래 내부 테이블 규칙).
- 결과는 `run_claim`을 UPDATE하지 않고 **별도 추가 전용 테이블 `run_result`에 INSERT**한다. UPDATE는 행을 찾느라 인덱스를 읽어 같은 거짓 충돌을 다시 만든다.
- 재생으로 얻은 토큰의 LSN은 새로 조회한다. 저장된 값은 커밋 전에 잡힌 것이라 낮다.
- `then`과 `@process` 디스패처는 **작업 ID를 실행 ID로** 쓴다. 그래서 작업 완료 기록과 펜싱도 `run_claim` 하나로 끝난다(§4.10).
- 두 테이블은 보존 기간(재실행이 일어날 수 있는 최대 기간보다 길게)이 지나면 정리한다.

> **내부 추가 전용 테이블 규칙**: `run_claim`, `run_result`, outbox 로그, 작업 테이블은 **SERIALIZABLE 트랜잭션 안에서 읽지 않는다.** SERIALIZABLE은 B-tree 리프 페이지 단위로 읽기 잠금을 걸고, uuid7처럼 커지는 키는 모든 INSERT가 맨 오른쪽 페이지에 몰린다. 그 페이지를 읽는 트랜잭션들끼리 서로의 읽기를 무효로 만드는 순환이 생겨, 서로 무관한 커맨드들이 직렬화 실패로 재시도된다. SERIALIZABLE 트랜잭션 안에서 이 테이블들에 하는 일은 INSERT뿐이고, 읽기는 별도 READ COMMITTED 트랜잭션에서 한다. (소비자 체크포인트와 작업 리스는 갱신하지만, SERIALIZABLE이 아닌 별도 트랜잭션에서만 한다, §8.4.)

#### 합성: 단계는 `chain`으로만 (JPA `REQUIRED`에 해당)

```python
@step
def apply_coupon(order: Order, coupon: Coupon) -> Changes:
    return order.set(Order.total.to(coupon.apply(order.total))) + coupon.set(Coupon.used.to(True))

@usecase
def checkout(order: PayableOrder, coupon: Annotated[Coupon, Load()],
             wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    with chain(order, wallet) as (c, order, wallet):    # 같은 이름으로 다시 묶인다
        c.run(apply_coupon, order, coupon)
        c.run(pay, order, wallet, now)                  # order: 쿠폰이 반영된 최신 상태
    return c.changes
```

- **위치 인자 + 같은 이름 재바인딩.** `chain(*snapshots)`은 TypeVarTuple로 타입이 붙어, 돌려받는 `order`, `wallet`이 각각 `Order`, `Wallet`으로 보인다. 원래 이름을 덮어쓰므로 "원본을 실수로 읽는" 경우가 구조적으로 대부분 사라진다.
- 돌려받는 값은 **항상 chain의 최신 상태를 가리키는 뷰**다. 평범한 스냅샷이면 `c.run` 다음 줄에서도 예전 값이라 재바인딩이 의미가 없다. `c.run`에 넘길 때는 그 시점의 불변 스냅샷으로 바뀌어 전달된다.
- **이동 표시**는 별칭 방어용으로 남는다. `o = order`처럼 chain 전에 만든 별칭으로 필드를 읽으면 `MovedSnapshotAccess`다. 변경 전 값이 필요하면 `c.original(order)`.
- **블록을 벗어난 뒤**: 뷰는 최종 상태로 고정되어 **읽기는 허용**(`Changes.returning(order.total)` 등), **`.set`은 에러**다. 블록 밖의 쓰기는 `c.changes`에 들어가지 않고 조용히 사라지기 때문이다.
- `c.changes`는 원래 스냅샷 대비 최종 차이로 합쳐진다. 이벤트는 발생 순서대로 모두 남는다.
- **단계끼리 `+`는 타입 에러다.** 단계 호출 결과(`StepResult`)에는 `+`가 없다. 데코레이터 없는 헬퍼끼리의 `+`는 린트(`PRL001`)로 잡는다.

#### 커밋 후 별도 트랜잭션 (JPA `REQUIRES_NEW`, `AFTER_COMMIT`에 해당)

```python
@usecase
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    return (
        order.set(Order.status.to(OrderStatus.PAID))
        + then(issue_receipt.bind(order=Order.ref(order.id)))   # 커밋 성공 후 별도 트랜잭션
    )
```

`then`은 outbox 로그에 명령으로 기록되고, 작업 파이프라인(§4.10)이 커밋 이후 새 트랜잭션으로 실행한다. 바깥 트랜잭션이 롤백되면 기록되지 않는다.

#### 요청 사이 낙관적 락

```python
@api.put("/orders/{order_id}")
async def edit_order(order_id: UUID, body: EditOrder, if_match: int = Header()):
    await app.run(edit.bind(order=Order.ref(order_id, expected_version=if_match), patch=body))
```

두 요청을 잇는 트랜잭션이 없으므로 DB가 감지할 수 없는 lost update를 `version`으로 막는다. `owned` 자식의 변경도 루트 버전을 올리므로, 항목만 바뀐 경우도 걸린다.

#### 조회 트랜잭션

```python
rows = await app.query(orders.summaries(user_id=uid))                # 서술을 만들고
rows = await app.query(orders.summaries(user_id=uid), after=token)   # 실행 옵션은 따로

async with app.read(consistency="snapshot") as r:                    # REPEATABLE READ READ ONLY
    summary = await r.query(orders.summaries(user_id=uid))
    stats   = await r.query(sql.order_stats(since=day))
```

- 단일 조회는 READ COMMITTED(레플리카 가능), 여러 조회를 한 시점으로 묶을 때는 `app.read(consistency="snapshot")`.
- `app.read(consistency="serializable")`는 `SERIALIZABLE READ ONLY DEFERRABLE`로 실행한다.

#### 예외 처리

| 상황 | 동작 |
|---|---|
| 도메인 예외 (usecase가 raise) | 롤백, 그대로 전파, 재시도 없음 (작업 러너에서의 처리는 §4.10) |
| 40001 직렬화 실패 / 40P01 데드락 | 롤백 후 처음부터 재시도. 한도 초과 시 `RetryExhausted` |
| 23505 (실행 ID 테이블) | 멱등 경로: 저장된 결과 반환 |
| 23505 (그 외) | `retry.on_unique=True`일 때만 재시도, 아니면 `UniqueViolation` |
| 루트 ref나 필수 의존 로드의 행이 없음 | `NotFound` |
| `expected_version` 불일치 | `VersionMismatch`, 재시도 없음 (사용자에게 충돌을 알려야 함) |
| COMMIT 중 연결 끊김 | 같은 실행 ID로 재실행 (위 참조) |
| ref의 필드 읽기 / ref에 `.set` / ref에 `==`나 `hash()` | `UnloadedReference` |
| 이동된 원본(별칭)으로 필드 읽기 (`==`, `hash()` 포함) | `MovedSnapshotAccess` |
| 커밋 전 `identity` 키 새 엔티티의 `hash()` | `UsageError` (ADR-0003) |
| chain 블록 밖에서 뷰에 `.set` | `ChainClosed` |
| 한 단계 안에서 같은 필드를 두 번 씀 | `ConflictingWrites` |
| 같은 유스케이스 안의 집합 변경·행 변경 겹침 | `IntraUsecaseConflict` |
| 취소 (타임아웃, 클라이언트 끊김) | 로드·계산 중이면 롤백. 커밋 배치는 shield돼서 끝까지 진행 |

#### Spring/JPA 대응표

| Spring / JPA | Platina |
|---|---|
| `@Transactional` (REQUIRED) | `app.run(uc.bind(...))` 1회. 내부 합성은 `chain` |
| `propagation = REQUIRES_NEW` | `then(uc.bind(...))` |
| `@TransactionalEventListener(AFTER_COMMIT)` | async 프로젝션 / `@process` |
| `propagation = NESTED` (savepoint) | 미지원 |
| `readOnly = true` | `app.query` / `app.read` |
| `isolation`, `timeout` | `@usecase(isolation=..., timeout=...)` |
| `rollbackFor` | 도메인 예외는 항상 롤백 |
| `@Retryable` | 내장 (40001/40P01) |
| `@Version` + detached 엔티티 병합 | `Order.ref(id, expected_version=v)` |
| `LockModeType.OPTIMISTIC_FORCE_INCREMENT` | `one_to_many(..., owned=True)` |
| `@Lock(PESSIMISTIC_WRITE)` | `Profile(..., lock="for_update")` |
| `EntityManager.getReference()` | `Order.ref(id)`, `orders.by_number(n)` |
| 영속성 컨텍스트 flush | 없음. 커밋 배치에서 ChangeSet이 한 번에 적용 |

### 4.7 부분 로드와 의존 로드

제너레이터는 없다. 추가로 필요한 데이터도 **선언**한다. 로드 단계 수는 seal 시점에 확정된다.

```python
# 부분 로드: 컬렉션 전체를 읽지 않음
type OrderWithCount = Annotated[Order, orders.with_item_count]

@usecase
def add_item(order: OrderWithCount, sku: str) -> Changes:
    if order.items.count >= 100:
        raise TooManyItems(order.id)
    # 미결(#49): owned 자식이 부모 키를 얻는 방법(스파이크 0001 F2) - 지금은 `order_id` 없이는 타입 에러
    return order.set(Order.items.add(Item(sku=sku, price=..., position=order.items.count)))

# 식 형태: 조건과 매칭이 컬럼 식이면 서브쿼리로 접혀 추가 왕복이 없다
type PointWallet = Annotated[Wallet | None,
    Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id == Order.user_id)]
    # 미결(#51): 컬럼 대 컬럼 비교 피연산자(스파이크 0001 L5) - 지금은 두 컬럼 사이의 `==`가 타입 에러

# 함수 형태(Load.after): 식으로 표현하기 어려울 때. 인자 이름이 유스케이스 파라미터에 바인딩됨
def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.paid_with is PaymentMethod.POINT else None

type PointWalletAfter = Annotated[Wallet | None, Load.after(point_wallet)]   # 로드 단계 1개 추가

@usecase
def refund(order: Annotated[Order, Load(Order.items)], wallet: PointWallet) -> Changes:
    changes = order.set(Order.status.to(OrderStatus.REFUNDED))
    if wallet is not None:
        changes += wallet.set(Wallet.balance.path(Money.amount).add(order.total.amount))
    return changes

# 재귀 로드
type RoleTree = Annotated[list[Role], Load.recursive(start=User.roles, via=Role.parent, max_depth=10)]
```

- **식 형태**는 같은 엔티티 타입의 파라미터가 하나일 때만 허용한다. 둘 이상이면 seal 에러를 내고 `Load.after`를 안내한다.
- **함수 형태**는 인자 이름이 유스케이스 파라미터에 바인딩되고(seal 검사), 타입을 단 함수를 권장한다(람다 인자는 `Any`로 추론됨). 함수는 순수해야 하며 ref나 `None`을 돌려준다.
- **`None`과 `NotFound`를 구분한다.** 조건이 거짓이거나 함수가 `None`을 돌려주면 `None`, 조건은 참인데 행이 없으면 `NotFound`. 없어도 되면 `Load.after(fn, missing="none")`.
- 이걸로도 표현할 수 없는 "데이터를 끝없이 따라가는" 로직은 한 유스케이스에 담을 수 없다(§7.1).

### 4.8 대량 쓰기

```python
@usecase
def import_products(rows: list[ProductRow]) -> Changes:
    return insert_all(Product(sku=r.sku, price=r.price) for r in rows)   # COPY, 청크 스트리밍

@usecase
def expire_orders(now: Now = INJECTED) -> Changes:
    return orders.expire_older_than(now - timedelta(days=30))   # Repository의 집합 변경 팩토리

@batch_usecase(chunk=5_000, cursor=Account.id, job="apply-interest-2026-11")
def apply_interest(accounts: Chunk[Annotated[Account, Load(Account.product)]]) -> Changes:
    return changes(a.set(Account.balance.add(calc_interest(a))) for a in accounts)   # balance: Col[Decimal]

await app.run_batch(apply_interest)   # 청크마다 커밋, 체크포인트는 같은 트랜잭션에 기록, 재시작 시 이어서
```

집합 변경의 `emit_each`는 `UPDATE … RETURNING id, version`의 결과로 이벤트 순서 번호를 채워 outbox INSERT에 넘긴다(한 문장의 CTE).

### 4.9 TypedSQL과 t-string

```sql
-- shop/billing/queries/order_stats.sql
-- name: order_stats
SELECT date_trunc('day', created_at) AS day, count(*) AS orders, sum(total_amount) AS revenue
FROM orders
WHERE created_at >= :since
GROUP BY 1
ORDER BY 1;
```

```python
from shop.billing.generated import sql          # platina gen 결과 (저장소에 커밋됨)

stats: list[sql.OrderStatsRow] = await app.query(sql.order_stats(since=date(2026, 11, 1)))

# 즉석 쿼리: t-string + DTO, 컬럼은 런타임에 검증
rows = await app.query(raw(OrderSummary, t"SELECT id, number, total_amount AS total, 0 AS item_count FROM orders WHERE user_id = {uid}"))
```

### 4.10 이벤트 소비: 프로젝션, then, process

#### 프로젝션: 대상과 키를 선언하고, 본문은 필드 연산만

```python
@projection(on=OrderPaid, into=UserSpending, key=OrderPaid.user_id)    # 기본 inline: 같은 트랜잭션
def user_spending(e: OrderPaid) -> Ops[UserSpending]:
    return (UserSpending.total.add(e.total.amount),)

@projection(on=OrderPaid, into=DailyRevenue, key=lambda e: e.paid_at.date(), mode="async")
def daily_revenue(e: OrderPaid) -> Ops[DailyRevenue]:                  # 날짜 키 집계는 async로
    return (DailyRevenue.total.add(e.total.amount),)

@projection(on=OrderPaid, into=DailyRevenue, key=lambda e: e.paid_at.date(),
            allow_hot_key="트래픽이 낮고 일별 합계의 강한 일관성이 필요함")   # 명시적 opt-in
def daily_revenue_strict(e: OrderPaid) -> Ops[DailyRevenue]: ...
```

- **대상(`into`)과 키(`key`)는 선언에, 본문은 그 행에 대한 필드 연산만.** 본문이 다른 키로 upsert하는 식의 우회가 불가능해서 seal이 핫 로우 규칙을 정확히 검사할 수 있다. 행 여러 개를 갱신해야 하면 프로젝션을 나눈다.
- **inline 키 규칙**: 이벤트의 엔티티 ID 필드만 허용. 날짜·상수 같은 파생 키는 seal에서 거부(async 또는 `allow_hot_key`). 엔티티 ID도 뜨거울 수 있으므로 **프로젝션별 재시도율 메트릭**은 항상 낸다.
- **async 프로젝션 소비자**는 직렬 경로다. 로그를 별도 READ COMMITTED 트랜잭션에서 읽고, 효과와 체크포인트를 **REPEATABLE READ** 트랜잭션에 함께 커밋한다(필드 연산이 교환 가능하고 체크포인트마다 소비자가 하나라 SERIALIZABLE이 필요 없다). 독성 메시지가 오면 건너뛰지 않고 **멈추고 알린다.** 건너뛰면 읽기 모델이 틀어진다.

#### then과 process: 2계층 작업 파이프라인

```python
@process(on=PaymentRequested)                       # 외부 IO가 허용되는 유일한 장소
async def approve_payment(e: PaymentRequested, ctx: ProcessContext, pg: PgClient) -> Bound | None:
    res = await pg.approve(e.payment_key, e.amount, idempotency_key=ctx.idempotency_key)
    if res.ok:
        return confirm_payment.bind(order=Order.ref(e.order_id), approval=res.id)
    return cancel_order.bind(order=Order.ref(e.order_id), reason=res.code)
    # app.run을 부르지 않는다. 돌려준 서술을 디스패처가 완료 기록과 한 트랜잭션에 커밋한다.

class InsufficientBalance(DomainError, retry_later=RetryLater(max_attempts=5, within="1h")): ...
```

```
outbox 로그 ─[로그 리더: xid 워터마크, READ COMMITTED]→ 핸들러별 작업 테이블 INSERT (+ 리더 체크포인트, 같은 트랜잭션)
작업 테이블 ─[워커: 짧은 READ COMMITTED 트랜잭션으로 리스 획득, SKIP LOCKED]→ 핸들러 실행 (외부 IO는 트랜잭션 밖)
           ─[디스패처: 작업 ID를 실행 ID로 해서 돌려받은 유스케이스 실행. run_claim이 곧 완료 기록]→ 완료
```

- **process는 서술을 돌려준다.** 디스패처가 그 유스케이스와 완료 기록을 한 트랜잭션에 커밋하므로, 커밋된 뒤에는 재전달 자체가 없다. 흔한 형태(IO 후 유스케이스 하나)에서는 키 설계가 필요 없다. 유스케이스가 여럿이면 `then`으로 잇는다. 디스패처는 실행기를 import하지 않는다. 묶인 유스케이스를 실행 ID로 실행하는 함수를 `app`이 넘겨준다(ADR-0001).
- **외부 멱등성은 따로 필요하다.** 외부 IO는 끝났는데 디스패처가 커밋하기 전에 죽으면 재전달되고, 외부 호출이 반복된다. 그래서 프레임워크가 이벤트 기반 `ctx.idempotency_key`를 주고, 외부 호출에 이 키를 쓰는 것을 규칙으로 한다. 멱등 키를 받지 않는 외부 API는 "상태를 먼저 조회한 뒤 판단"으로 짠다.
- **리스는 트랜잭션 밖에서.** 행 락을 쥔 채 외부 IO를 기다리면, 그 트랜잭션이 xid를 가진 채 열려 있어 로그 리더의 xid 워터마크 전체가 멈춘다. 리스 획득과 완료 기록은 각각 짧은 트랜잭션이다.
- **완료 기록과 펜싱은 `run_claim` 하나로.** 디스패처는 작업 ID를 실행 ID로 쓰므로, 유스케이스 트랜잭션의 첫 문장인 `run_claim` INSERT가 곧 완료 기록이다. 리스가 만료돼 두 워커가 같은 작업을 끝내면, 늦은 쪽은 23505를 받고 아무것도 하지 않는다(먼저 온 쪽이 아직 진행 중이면 유니크 키에서 기다렸다가 결정된다). 핸들러가 `None`을 돌려줘도 디스패처는 `run_claim`만 담은 트랜잭션을 커밋해 완료를 남긴다. 리스 토큰을 읽지 않으므로 내부 테이블 규칙을 지킨다.
- **같은 집계 안의 순서**: 집계 키마다 가장 앞선 작업 하나만 처리 중일 수 있다(예: 같은 주문의 `PaymentCancelled`가 `PaymentRequested`를 앞지르지 않음).
- **실패 종류 구분**:
  - 일시적 오류(연결, 타임아웃, 40001 한도 초과): 백오프 재시도.
  - 도메인 예외: 기본은 즉시 dead-letter. 예외 타입이 `retry_later=RetryLater(max_attempts, within)`를 선언했을 때만 나중에 재시도한다. 이 설정은 작업 러너에서만 의미가 있고, HTTP에서 부른 `app.run`에서는 즉시 전파된다. 상한을 넘으면 dead-letter.
  - 맨 앞 작업이 dead-letter로 가면 **그 키의 뒤 작업도 막는다.** 피해가 집계 하나로 격리된다. "막힌 키 수" 메트릭과, 감사 기록을 남기며 다시 보내거나 건너뛰는 운영 도구를 함께 제공한다.
- `then` 유스케이스는 유스케이스 의미론 그대로 SERIALIZABLE로 실행된다.
- `pg: PgClient`처럼 외부 의존성은 `app.provide(PgClient, factory)`로 등록해 주입한다. 유스케이스에는 이런 주입이 없다.

### 4.11 웹 프레임워크 통합 (FastAPI 예)

```python
from fastapi import FastAPI, Header
from platina.integrations.fastapi import lifespan, ConsistencyTokenMiddleware

api = FastAPI(lifespan=lifespan(app))           # 기동 시 app.seal(), 종료 시 풀 정리
api.add_middleware(ConsistencyTokenMiddleware)  # X-Consistency-Token 헤더 ↔ contextvar

@api.post("/orders/{order_id}/pay")
async def pay_order(order_id: UUID, idem: str = Header(alias="Idempotency-Key")):
    await app.run(pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(current_user().id)),
                  idempotency_key=idem)
    return {"ok": True}                         # 미들웨어가 result.token을 응답 헤더에 실음

@api.get("/orders")
async def list_orders():
    return await app.query(orders.summaries(user_id=current_user().id))   # 요청 헤더의 토큰 자동 적용
```

### 4.12 테스트

```python
# 단위 테스트: DB 없음. 유스케이스와 step은 직접 호출하면 StepResult를 돌려준다
def test_pay_moves_balance():
    order = Order.stub(status=PENDING, total=Money(Decimal("1000")))
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = pay(order, wallet, now=datetime(2026, 11, 24))
    assert r.updated(order) == {Order.status: PAID, Order.paid_at: datetime(2026, 11, 24)}
    assert r.updated(wallet) == {Wallet.balance: Add(Decimal("-1000"))}
    assert r.events == [OrderPaid(order_id=order.id, user_id=order.user_id,
                                  total=order.total, paid_at=datetime(2026, 11, 24))]

def test_checkout_charges_discounted_total():
    order, coupon = Order.stub(total=Money(Decimal("1000"))), Coupon.stub(rate=Decimal("0.1"))
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = checkout(order, coupon, wallet, now=NOW)
    assert r.updated(wallet) == {Wallet.balance: Add(Decimal("-900"))}   # chain 덕분에 할인 금액으로 차감

def test_alias_of_moved_snapshot_is_rejected():
    @usecase
    def bad(order: PayableOrder, wallet: ChargeableWallet) -> Changes:
        alias = order
        with chain(order, wallet) as (c, order, wallet):
            c.run(charge, wallet, alias.total)            # chain 전에 만든 별칭
        return c.changes
    with pytest.raises(MovedSnapshotAccess):
        bad(Order.stub(), Wallet.stub())

# Repository 테스트: 생성 SQL 스냅샷 (DB 없음)
def test_summaries_sql(snapshot):
    assert orders.summaries(user_id=uid).compile() == snapshot

# 통합 테스트: 실제 PostgreSQL + 왕복 예산
async def test_pay_roundtrips(app_with_db):
    with app_with_db.expect_roundtrips(max=2):          # 로드 1 + 커밋 배치 1
        await app_with_db.run(pay.bind(order=..., wallet=...))
```

### 4.13 에러 메시지 예시

```
RelationNotLoaded: Order.items는 로드되지 않았습니다.
  유스케이스: shop/billing/usecases.py:12  (pay)
  실제 로드 선언: Load()  ·  필요한 선언 예: orders.payable = Profile(Order.items, Order.user)
  해결: Annotated[Order, orders.payable] 사용 또는 Load(Order.items) 추가

MovedSnapshotAccess: alias는 chain으로 이동된 order의 별칭입니다. Order.total을 읽었습니다.
  위치: shop/billing/usecases.py:31  (checkout)
  해결: chain이 돌려준 order를 사용하거나, 변경 전 값이 필요하면 c.original(order)

UnloadedReference: Order.ref(...)에 .set을 호출했습니다. ref는 로드 요청일 뿐입니다.
  해결: 유스케이스 파라미터로 받아 로드하거나, Order.where(Order.id == x).set(...)로 명시

SealError: inline 프로젝션 daily_revenue의 키가 엔티티 ID가 아닙니다 (date).
  해결: mode="async" 또는 allow_hot_key="사유"

SealError: 집합 변경이 불변식으로 보호된 필드를 수정합니다.
  위치: shop/billing/repos.py:41  (OrderRepo.expire_older_than)
  필드: Order.status  ← @invariant paid_requires_total (entities.py:29)
  해결: 불변식을 Check(...)로 옮기거나 .set(..., unsafe_bypass="사유") 명시

SealError: Load.when 식이 모호합니다. refund_merge에는 Order 타입 파라미터가 둘(src, dst) 있습니다.
  해결: Load.after(함수)로 어느 파라미터인지 명시

ModuleBoundaryError: shop.catalog.usecases.restock 이 billing 모듈의 엔티티 Order 를 로드합니다.
  해결: billing 이 공개한 조회(orders.summaries)를 사용하거나 이벤트로 통신
```

---

## 5. 비동기

### 계층별 선택

| 계층 | 선택 |
|---|---|
| 코어 (로드 계획, ChangeSet, SQL 컴파일) | **sans-IO**, 비동기 라이브러리 의존 없음 |
| async 실행기 | **anyio** API로 작성 (취소 의미론·구조적 동시성) |
| 백엔드 | **asyncio 전용**, uvloop은 사용자 선택 |
| sync 실행기 | psycopg sync 연결 직접 사용, 1급 경로 |
| 드라이버 | **psycopg 3.3+** 단일 |

### anyio를 쓰는 이유
- **취소 의미론**: 커밋·롤백 구간을 `CancelScope(shield=True)`로 보호
- **구조적 동시성**: 독립적인 로드를 task group으로 병렬 실행, 실패 시 깔끔한 취소

```python
async def run(bound: Bound[P], *, idempotency_key: str | None = None) -> RunResult:
    run_id = RunId.caller(idempotency_key) if idempotency_key else RunId.auto()
    async with pool.connection() as conn:
        return await drive_async(run_usecase(bound, run_id, policy, PG), conn)
    # 엔진(§10.5)이 명령을 내고, drive_async가 커밋 배치·롤백 구간에 shield를 건다
```

### 함수 색깔 문제 해소
도메인 함수는 IO도 없고 제너레이터도 아니다(의존 로드는 선언으로 한다). 그래서 sync/async는 물론 어떤 색에도 물들지 않고, 유스케이스와 step은 평범한 함수로 `chain`에서 자유롭게 합성된다.

### 파이프라인
로드 계획이 실행 전에 확정되므로 psycopg 파이프라인 모드로 계획의 각 단계를 한 번의 왕복에 보낸다. 식 형태 의존 로드(`Load.when`)는 같은 단계에 서브쿼리로 접히고, `Load.after`만 단계를 하나 더한다. 커밋 시 INSERT·UPDATE·outbox도 파이프라인으로 묶는다. 단, `COPY`는 파이프라인에서 지원되지 않으므로 대량 삽입은 별도 경로.

---

## 6. 지원 대상

### 런타임
- **Python 3.14+**: t-string(PEP 750), 지연 평가 어노테이션(PEP 649/749), free-threaded 공식 지원
- **PostgreSQL 14+**: 클라이언트 libpq 14 이상이 파이프라인 모드 요건. 서버도 `WITH RECURSIVE … CYCLE` 등을 위해 14+

### 기존 ORM과의 공존 (독립 ORM 기준)
- 어댑터를 만들지 않는다. 대신 **같은 DB를 함께 쓰는 공존**만 지원한다
  - `platina pull`: DB 카탈로그를 읽어 엔티티 정의를 생성 (Django·SQLAlchemy가 관리하던 DB 모두 동일하게 동작)
  - `version` 증가 **DB 트리거** 생성: 다른 ORM의 쓰기도 낙관적 락에 걸리게 함
  - 주의: SERIALIZABLE의 보장은 SERIALIZABLE 트랜잭션끼리만 성립하므로, 다른 ORM이 쓰는 테이블에선 `version` 트리거가 실질적 안전장치
- CRUD·어드민은 기존 ORM에 두고, 핵심 유스케이스만 Platina로

### 단계별 도입 (계단)

| 단계 | 도입하는 것 | 얻는 것 |
|---|---|---|
| 0 | `platina pull` + 조회 경로(TypedSQL)만 사용 | 타입 붙은 SQL, 쿼리 계측 |
| 1 | 로드 선언 + 유스케이스 1개 | N+1의 구조적 제거, 파이프라인 |
| 2 | 유스케이스 확대 + `chain` | DB 없는 테스트, 자동 재시도 |
| 3 | inline 프로젝션·outbox | 감사, 읽기 모델 |
| 4 | async 프로젝션·process·모듈 경계 | 서비스 분리 준비 |

> 독립 ORM을 택했으므로 "기존 ORM에 플러그인을 얹는 0단계"는 사라졌다. 대신 조회 경로부터 들어오는 것이 가장 낮은 진입점이다.

### 타깃 사용자
- **주 타깃**: "지금은 모놀리스로 빠르게, 나중에 떼어낼 때 고통 없이"를 원하는 팀
- **잘 맞는 도메인**: 주문, 원장, 예약, 정산, 결제
- **목표**: "돈과 정합성이 걸린 20%를 이걸로"
- **경쟁하지 않는 영역**: 단순 CRUD·어드민

---

## 7. 한계

### 7.1 데이터를 따라가며 판단하는 도메인
의존 로드를 선언(식·함수·재귀)으로만 허용했기 때문에, 모든 유스케이스의 왕복 단계 수가 seal 시점에 확정된다. 대가로, 깊이를 미리 알 수 없게 데이터를 따라가는 로직(재귀 CTE로도 표현되지 않는 탐색)은 한 유스케이스에 담을 수 없다.

이때 유스케이스를 둘로 나누는 건 불편함에서 끝나지 않고 **원자성을 잃는다.** 첫 트랜잭션에서 읽은 값이 두 번째 트랜잭션의 쓰기를 보호하지 못한다. 그래서 이런 로직은 재귀 CTE·TypedSQL로 DB 안에서 계산하거나, 두 번째 유스케이스가 전제를 다시 로드해 검증하도록 설계해야 한다.

### 7.2 외부 세계와의 상호작용
외부 결과가 쓰기를 결정하는 흐름은 process 핸들러와 여러 유스케이스로 쪼개진다. JPA의 메서드 하나가 이벤트 흐름이 되는 비용은 그대로 남는다.

### 7.3 SERIALIZABLE 기본값의 비용
경합이 심한 테이블에서는 직렬화 실패와 재시도가 늘어난다. 핫 로우에는 `lock="for_update"`나 `isolation=REPEATABLE_READ` + `version`으로 내려가야 하고, 후자는 write skew를 막지 못한다. inline 프로젝션이 만드는 핫 로우는 키 규칙(§4.10)으로 대부분 막지만, 엔티티 ID 키도 뜨거울 수 있다. 이 비용이 실제로 얼마인지는 벤치마크로 확인해야 한다(§9).

### 7.4 대량 쓰기의 남은 문제
- 집합 기반 갱신은 `@invariant`가 없는 필드에만 허용
- 청크 커밋은 체크포인트·멱등성으로 처리하지만, 작은 Spring Batch를 직접 운영하는 셈

### 7.5 결정적 한계: ORM이 아니라 아키텍처
"암묵적 IO 없음"과 "불변 엔티티"는 점진적일 수 없고, 가변 모델을 전제하는 생태계(Django admin, DRF, factory_boy)와 맞지 않는다. 독립 ORM을 택했으므로 기존 코드베이스에 스며드는 경로는 "같은 DB 공존"뿐이다.

### 7.6 범위 제한에서 오는 한계
- 초기에는 PostgreSQL 전용(MySQL은 시점 미정), psycopg 전용, asyncio 전용
- 빌드에 코드젠 단계 추가, 코드젠에는 임시 DB 필요(생성물은 커밋)

### 7.7 인프라 테이블의 비용
- 모든 커맨드가 실행 ID 행을 INSERT한다(호출자 키면 결과 행까지 2줄). 보존 기간이 지난 행은 정리 작업이 필요하다.
- `then`·`@process` 이벤트는 핸들러별 작업 테이블로 한 번 더 복사된다. 쓰기 증폭과 정리 비용이 생긴다.
- 오래 열린 쓰기 트랜잭션 하나가 xid 워터마크를 붙잡으면 모든 소비자가 그만큼 지연된다.
- 이 비용들은 "감지보다 제거"의 대가다. 실행 ID 하나로 멱등성과 커밋 판정을 처리하고, 작업 테이블로 독성 메시지를 격리하는 대신 쓰기가 늘어난다. 실제 크기는 §9의 실험으로 잰다.

---

## 8. 결정 기록

### 8.1 정체성

**형태: 독립 ORM (런타임), 스키마 도구는 SQLAlchemy Core + Alembic (선택 extra)**
- 결정: 쿼리 컴파일러와 실행 엔진은 SQLAlchemy에 의존하지 않고 직접 만든다. 컴파일러에는 방언 계층을 두되 첫 구현은 PostgreSQL 방언 하나로 시작한다. DDL·리플렉션·마이그레이션은 `platina[migrate]` extra에서 SQLAlchemy Core와 Alembic을 쓴다(§8.5).
- 근거: 실행 엔진은 파이프라인 단위로 명령을 내는 sans-IO 상태 기계라 SQLAlchemy의 실행 계층(DBAPI 커서, greenlet 기반 async)과 맞지 않는다. 쿼리 AST는 PostgreSQL 전용의 제한된 집합이고 불변 객체 그대로 로드 계획이자 캐시 키가 되므로 직접 만드는 비용이 작다. 반면 DDL·카탈로그 리플렉션·마이그레이션은 직접 만들 때 비용이 가장 큰 부분이라 Core와 Alembic을 쓴다.
- 바로잡은 점: 이전 근거("SQLAlchemy의 Session·identity map과 충돌")는 틀렸다. Session은 ORM 계층의 것이고 Core에는 없다. 리뷰에서 이 점이 지적돼 근거를 다시 세웠고, 그 과정에서 스키마 도구를 Core에 맡기는 혼합안으로 결정이 바뀌었다.

**이름: Platina**
- 결정: 패키지·import 이름 `platina`, CLI도 `platina`. 선택 extra는 `platina[migrate]`, 공식 플러그인은 `platina-pydantic`, `platina-saga`.
- 근거: platina는 백금이 처음 유럽에 알려질 때의 스페인어 이름("작은 은")이다. 백금의 성질 세 가지가 설계와 겹친다.
  - **반응하지 않는 귀금속**: 산에도 잘 녹지 않고 녹슬지 않는다. 도메인 코드는 DB와 반응하지 않는다(순수 함수).
  - **촉매**: 반응을 일으키지만 자신은 소모되거나 변하지 않는다. ORM이 트랜잭션을 돌려도 도메인은 그대로 남는다.
  - **표준의 원기**: 예전 국제 킬로그램 원기가 백금-이리듐 합금이었다. "Python ORM에는 JPA 같은 표준이 없다"에서 출발한 프로젝트와 이야기가 이어진다.
- 확인: 2026-11-25 기준 PyPI에 `platina`가 없다. GitHub에는 같은 이름의 라이브러리가 없고, 샤오미 기기 코드명으로 쓰인 커널 저장소 정도만 있다.
- 검토한 후보:
  - `purelational`(Pure + Relational, 첫 이름), `teduri`(테두리 = 경계): 다른 이름을 찾기로 하고 교체.
  - `munjigi`(문지기), `maedeup`(매듭), `purrm`(pure + ORM): 사용 가능했지만, platina가 "도메인은 순수하다"는 첫 번째 원칙을 성질로 설명해 더 핵심을 짚는다.
  - `platinorm`, `baekgeum`(백금): 사용 가능하지만 각각 접미사가 직설적이고, 로마자 표기가 해외 사용자에게 어렵다.
  - `platinum`, `iridium`, `rhodium`, `osmium`, `palladium`, `dojang`, `airlock`, `sluice`: PyPI에 이미 있음. `platine`: 독일어로 "회로 기판"이라 혼동. `edgewise`: EdgeDB용 ORM이 이미 사용. `docket`: 같은 이름의 Python 작업 라이브러리가 있음.
- 후속 조치: 실제 동작하는 최소 버전(0.0.1)으로 PyPI에 등록해 이름을 확보한다. 빈 패키지로 이름만 선점하는 것은 PEP 541상 회수 대상이 될 수 있다.

**라이선스: Apache-2.0**
- 근거: 특허 조항이 있어 기업 채택에 유리하다. Hibernate도 ORM 7.0부터 LGPL에서 Apache 2.0으로 옮겼고, 이유로 Apache/Jakarta 생태계 등에서의 수용 확대를 들었다.
- 의존성 확인: psycopg(LGPL-3.0-only)는 동적 import 의존이라 Apache-2.0 배포에 문제 없음. anyio(MIT), import-linter(BSD-2), 선택 extra의 SQLAlchemy·Alembic(MIT) 호환.

### 8.2 코어 설계

**로드 선언 문법: `Annotated[Entity, Load(...)]`**
- 결정: 어노테이션에 호출식을 쓰지 않고 `Annotated` 메타데이터로 선언한다. 재사용은 PEP 695 `type` 별칭으로.
- 근거: mypy·pyright 모두 어노테이션 위치의 호출식을 잘못된 타입으로 거부한다. `Annotated`는 FastAPI `Depends`로 이미 익숙한 패턴이다.
- 구현: 데코레이터는 `annotationlib`의 `FORWARDREF` 형식으로 어노테이션을 읽고, 실제 해석은 seal 시점에 한다. Python 3.14부터 어노테이션은 지연 평가가 기본이라, 엔티티 간 순환 참조를 문자열 없이 쓸 수 있다.

**검증 시점: import 시점 → seal 시점**
- 결정: "import 타임이 Python의 컴파일 타임"이라는 초기 구상을 폐기하고, `app.seal()`(앱 기동)과 `platina check`(CI)에서 검증한다.
- 근거: Python 3.15에 명시적 lazy import(PEP 810)가 들어왔고 전역 lazy 모드 플래그도 있다. 이 플래그가 켜지면 모듈 실행 시점이 늦어져 import 부수효과에 기댄 검증을 믿을 수 없다. PEP 649의 지연 어노테이션도 같은 방향이다.

**필드 타입 표면: `Col[T]` 래퍼와 소유자 타입 컬럼**
- 결정: 엔티티·이벤트·값 객체의 모든 컬럼 필드는 `Col[T]`로 선언한다(`status: Col[OrderStatus] = column(...)`, `Money`의 `amount: Col[Decimal]`). 관계는 `Rel[...]`. 클래스 접근은 `Column[Owner, T]`이고, 소유자는 필드를 선언한 클래스다(`Order.status`: `Column[Order, OrderStatus]`). 인스턴스 접근은 `T`. 임베디드 값 안으로의 경로는 `Order.total.path(Money.amount)`(`Column[Order, Decimal]`)다. `Column`의 소유자 파라미터는 공변, 값 파라미터는 불변이며 타입 테스트로 고정한다(ADR-0004).
- 근거: 평범한 어노테이션이면 타입 체커가 클래스 접근(`Order.status`)도 `T`로 본다. 클래스에선 컬럼, 인스턴스에선 `T`로 보이려면 어노테이션 자체가 오버로드된 `__get__`을 가진 디스크립터 타입이어야 한다. SQLAlchemy 2.0의 `Mapped[T]`가 같은 이유로 존재한다. `.to()`, Finder, 프로젝션 키가 모두 이 위에 서 있다. 소유자는 `__get__`의 `owner` 인자에서 오므로, 연산(`Op[Owner]`), 술어, 관계가 자신이 속한 엔티티를 지닌다. 스파이크 0001이 이 모두를 pyright와 mypy에서 확인했다.
- **소유자를 검사하는 곳**: 타입으로는 수신자가 소유자를 고정하는 곳만 검사한다 - `order.set(...)`, `Entity.where(...)`, `SetChange.set(...)`, `SetChange.emit_each(...)`, 관계 연산, `Repository[E]`의 Finder, `path`. 한 호출의 여러 인자에서 소유자를 추론해야 하는 곳은 타입으로 검사하지 않는다: 쿼리(`select`/`join`/`where`)는 서술을 만들 때 검증하고(seal에서도 잡을 수 있는지는 #52), `Profile`, `Load`, `Index`, `Check`, `@invariant(fields=...)`는 seal이 검증한다. 이유(스파이크 0001, P-A): 한 호출에 두 엔티티의 컬럼을 주면 pyright는 소유자를 합집합 `Order | Item`으로, mypy는 공통 기반 `Entity`로 추론해, 같은 오용이 한 체커에서만 에러가 된다.
- 대가: 어노테이션이 길어지고, `Column`을 쓰는 곳마다 타입 파라미터가 둘이며, 값 객체가 `Col[...]` 필드를 선언하고, 값 객체 일부의 증감은 경로를 거친다(`Wallet.balance.path(Money.amount).add(n)`). `Order.total.amount`는 제네릭 컬럼으로 타입을 붙일 수 없다.

**생성 문법과 생성자 타입**
- 결정: 엔티티는 `Entity` 기반 클래스를 상속하고, 생성은 그 키워드 생성자(`Order(number=..., total=...)`)로 이벤트·값과 같다. `new`는 없다. 수정은 `.set` 하나. "방법은 하나"는 연산마다 적용한다. 생성과 수정은 다른 연산이다(ADR-0003).
- 근거: 필수 필드 누락은 엔티티를 만들 때 가장 흔한 실수라, "정확성 우선"에 따라 정적으로 잡혀야 한다. 생성까지 `Order(Order.sku.to(...), …)` 연산 문법으로 통일하자는 대안은 이 검사를 런타임으로 내리므로 기각했다. 별도 클래스 메서드 `new`는 생성자 시그니처를 복사해야만 타입을 붙일 수 있어, 그 옆에서 평범한 생성자도 타입 검사를 통과한다. `new`를 없애면 두 번째 방법을 감지하는 대신 제거한다.
- 타입 확보 순서: 1단계가 성립하므로(스파이크 0001) 2, 3단계는 필요 없다.
  1. **채택.** 디스크립터의 `__set__(self, instance: Never, value: T)`: `Entity`에 붙인 `dataclass_transform(kw_only_default=True, frozen_default=True, ...)`으로 합성된 생성자가 각 파라미터 타입을 `__set__`의 value에서 가져가고, 대입은 막힌다(pyright `reportAttributeAccessIssue`, mypy `misc`와 `arg-type`). 필드 지정자는 생성되는 키, `version_column()`, 서버 기본값, 관계에 `init: Literal[False]`를 선언하므로 이들은 파라미터가 아니다.
  2. 생성된 **진짜 Python 모듈**의 타입 붙은 생성 함수.
  3. 런타임 검사만 (마지막 수단).
- `.pyi` 스텁 생성은 기각했다. 스텁은 생성자만 덧씌우지 못하고 모듈의 타입을 통째로 대신해서, 필드를 추가하고 다시 생성하기 전까지 에디터가 예전 모습을 보여 준다.
- 엔티티는 타입 수준에서 해시 가능하다(`frozen_default=True`. 이것이 없으면 `{order}`에 대해 pyright와 mypy의 판단이 갈린다). 런타임 동등성은 스냅샷의 값(컬럼과 로드된 관계, 무엇이 로드됐는지까지 포함)을 비교하고, 해시는 엔티티 타입과 기본 키다. ref는 `UnloadedReference`를 내고, `identity` 키를 가진 새 엔티티는 커밋 전에 해시가 없으며(`UsageError`), chain 뷰는 최신 상태를 비교하고, 이동된 별칭은 `MovedSnapshotAccess`를 낸다(ADR-0003).
- 미결: `Order.stub(...)`의 키워드는 타입 검사되지 않고(#50), owned 자식이 부모 키를 얻는 방법(§4.7)은 정해지지 않았다(#49).

**의존 로드: 선언형만, 제너레이터 없음**
- 결정: 추가로 필요한 데이터는 `Load.when`(컬럼 식)이나 `Load.after`(타입 단 순수 함수)로 선언한다. 유스케이스 안에서 `yield`로 데이터를 요청하는 방식은 두지 않는다.
- 근거: 제너레이터 유스케이스는 새로운 함수 색깔이었다. `chain`에 그냥 넣을 수 없고, 호출하는 쪽도 제너레이터가 돼야 하며, send 타입이 하나라 `wallet = yield ...`의 타입도 추론되지 않았다. 선언으로 바꾸면 색깔이 사라지고, 파라미터 타입(`Wallet | None`)이 정확해지며, 왕복 단계 수가 모든 유스케이스에서 seal 시점에 확정된다.
- 식 형태는 같은 엔티티 타입의 파라미터가 하나일 때만 허용한다(둘이면 seal 에러 → `Load.after` 안내). 조건과 매칭이 컬럼 식이라 서브쿼리로 접혀 추가 왕복이 없다.
- 함수 형태는 인자 이름이 유스케이스 파라미터에 바인딩되고(seal 검사), 람다 대신 타입 단 함수를 권장한다(람다 인자는 `Any`로 추론됨).
- `None`과 `NotFound`를 구분한다. 조건이 거짓이면 `None`, 조건은 참인데 행이 없으면 `NotFound`. 없어도 되는 경우는 `missing="none"`으로 명시한다.
- 대가: 깊이를 알 수 없는 탐색은 표현할 수 없다(§7.1).

**재귀 로드**
- 결정: `Load.recursive(...)` → `WITH RECURSIVE`. `max_depth` 필수, PostgreSQL 14의 `CYCLE` 절로 순환 감지.

**외부 이펙트 범위**
- 결정: 유스케이스 안에서는 어떤 이펙트도 허용하지 않는다. 외부 IO는 `@process` 핸들러에서만 가능하고, 핸들러도 유스케이스를 직접 실행하지 않고 **서술을 돌려준다**(§8.4 작업 처리).
- 근거: 이펙트 요청(`Call(...)`)을 허용하는 순간 실행기가 이펙트 인터프리터가 되고, 트랜잭션 안에서 외부 IO를 기다리는 안티패턴이 열린다. "순수(usecase) / 비순수(process)" 두 종류로 고정하는 것이 철학과 맞는다.

**호출 문법: `bind` + 자리표시자 ref**
- 결정: 유스케이스 호출은 `uc.bind(...)`로 서술을 만들고 `app.run(서술, 옵션)`으로 실행한다. ref(`Order.ref(id)`, `orders.by_number(n)`)는 타입상 엔티티인 자리표시자이고, 실행기가 주입하는 파라미터는 기본값 `INJECTED`를 가진다.
- 근거: 이전 안(`app.run(pay, order=Order.ref(id))`)은 파라미터 타입을 `Order`에서 `Ref[Order]`로 바꾸고 `Now`를 빼야 했는데, ParamSpec은 이런 변환을 못 하고 `**kwargs: P.kwargs` 옆에 실행 옵션 키워드를 둘 수도 없다(PEP 612). ref를 타입상 엔티티로 두면 `bind`의 시그니처가 유스케이스와 같아져 ParamSpec만으로 검사된다. JPA `EntityManager.getReference()`와 같은 발상이다.
- Finder는 호출형(`orders.by_number("A-1")`)이라 인자가 컬럼 타입으로 검사된다.
- ref에 대한 `.set`도 `UnloadedReference`로 막는다. 필드를 읽지 않는 쓰기라 그냥 두면 로드와 `@invariant` 검사를 건너뛰는 쓰기가 된다. 로드 없는 쓰기는 `Order.where(Order.id == x).set(...)` 집합 변경으로 명시한다.
- 대가: ref의 필드를 호출 측에서 읽으면 런타임에서만(즉시, 결정적으로) 에러가 난다.

**쓰기 문법: `.set(Column 연산)` 하나**
- 결정: 쓰기는 `order.set(Order.status.to(PAID), Order.paid_at.to(now))`처럼 필드 연산을 넘기는 방식 하나다. 컬렉션도 `Order.items.add/remove/update` 연산으로 표현한다. 집합 변경(`Order.where(...).set(...)`)과 문법이 같다.
- 근거: `Col[T]` 디스크립터 덕분에 `Column[Owner, T].to(v: T)`로 이름과 타입이 코드젠 없이 검사되고, 스냅샷은 타입 수준에서도 불변으로 남는다.
- 검토 후 기각한 대안:
  - `.set(status=PAID)` 키워드 방식: 필드 이름 오타를 타입 체커가 못 잡는다.
  - `with order.edit() as o:`(Self 반환)로 대입: 대입을 허용하려면 컬렉션 필드 타입이 `list`여야 해서, 스냅샷의 `order.items.append()`까지 타입상 통과한다.
  - Immer식 `draft()`: 쓰기 방법이 둘이 되고, 위와 같은 이유로 타입 수준 불변성이 깨진다.
- 대가: 대입 문법보다 길다. 익숙함보다 "방법은 하나"와 타입 안전을 택했다.

**집계 경계: `aggregate_root`와 `owned`**
- 결정: `class Order(Entity, table="orders", aggregate_root=True)`와 `one_to_many(..., owned=True)`로 집계 경계를 선언한다. 하나의 선언이 세 곳에 쓰인다: ① `owned` 자식의 변경이 루트 `version`을 올림, ② `@event(aggregate=...)`의 순서 번호, ③ 모듈 경계 검사.
- 근거: 편집 화면이 주문과 항목을 같이 다룰 때 항목만 바뀐 경우도 요청 사이 낙관적 락에 걸려야 한다(JPA `OPTIMISTIC_FORCE_INCREMENT`). 하지만 모든 FK 자식에 적용하면 게시글에 댓글만 달아도 게시글 행을 갱신하게 되고, SERIALIZABLE 기본값에서 곧 핫 로우가 된다. 그래서 집계에 속한 자식으로만 한정한다.

**큰 집계의 부분 로드**
- 결정: `Load(Order.items.count())`, `.exists()`, `.where(...)` 같은 부분 로드를 제공. 추가·삭제 같은 쓰기 연산은 컬렉션을 로드하지 않아도 허용하고, 순회·조회는 로드가 필요.

**Python 전용 불변식 표시**
- 결정: `@invariant(fields=lambda: (Order.status, ...))`로 보호 필드를 명시(문자열 대신 참조). 집합 기반 갱신이 해당 필드를 건드리면 seal 시점 에러. SQL로 표현 가능한 규칙은 `Check(...)`로 선언해 DB `CHECK` 제약으로 내리고, 이런 필드는 집합 갱신을 허용.
- 탈출구: `.set(..., unsafe_bypass="사유")`. 사유는 ChangeSet과 감사 로그에 남는다.

**모듈 경계 선언**
- 결정: 패키지의 `__init__.py`에 `Module("billing", exposes=[...])`. 엔티티는 정의된 패키지의 모듈에 속한다. 로드 선언의 모듈 경계는 seal에서 검증하고, import 수준은 `platina contracts`가 생성한 import-linter 독립성 계약으로 검증.
- 근거: import 그래프 분석은 import-linter가 이미 잘 한다. 직접 만들 이유가 없다.

### 8.3 정합성·트랜잭션

**기본 격리 수준: Command는 SERIALIZABLE**
- 결정: 유스케이스는 기본 SERIALIZABLE로 실행하고, 직렬화 실패 시 자동 재시도한다. Query 경로는 READ COMMITTED.
- 근거: PostgreSQL은 SERIALIZABLE을 쓰는 애플리케이션이 직렬화 실패(SQLSTATE 40001)를 재시도할 준비가 돼 있어야 한다고 명시하고, 정확성을 보장할 수 없어 DB가 자동 재시도를 제공하지 않는다고도 밝힌다. 대부분의 ORM에서는 이 재시도가 위험하지만(트랜잭션 안의 부수효과가 반복됨), Platina의 유스케이스는 순수 함수라 전체 재실행이 안전하다.
- 효과: "읽기 범위 버전 검증" 같은 별도 기능이 필요 없다. write skew는 SSI가 막는다.
- 탈출구: `@usecase(isolation=REPEATABLE_READ)` + `version`, 또는 `lock="for_update"` 프로필. **READ COMMITTED는 Command에 허용하지 않는다.** 로드 계획의 문장마다 스냅샷이 달라 "로드한 스냅샷은 한 시점의 모습"이라는 전제가 깨진다. REPEATABLE READ는 write skew를 막지 못하므로, 읽기 집합에 기반한 규칙이 있으면 SERIALIZABLE에 남아야 한다.

**재시도 정책**
- 결정: 40001과 40P01은 무조건 재시도. 23505는 `on_unique=True`를 명시한 유스케이스만(실행 ID 테이블의 23505는 멱등 경로로 따로 처리). 최대 4회 시도, 지수 백오프 + full jitter(기준 10ms, 상한 200ms), 재시도마다 로드부터 다시.
- 근거: PostgreSQL 문서는 직렬화 실패는 무조건 재시도해도 좋지만, unique 위반 같은 다른 코드는 영구적 오류일 수 있어 더 주의해야 한다고 권한다.
- 이 재시도 루프와 작업 러너의 도메인 예외 재시도(`retry_later`, §8.4)는 별개다.

**같은 유스케이스 안의 커밋 순서**
- 결정: ① 집합 기반 변경(선언 순) → ② 행 단위 변경을 **FK와 유니크 키 의존성 그래프로 위상 정렬**한 순서 → ③ inline 프로젝션 → ④ outbox → ⑤ 실행 결과 기록. 같은 테이블·연산·컬럼 집합끼리는 배치로 묶는다(§10.7).
- 근거: Hibernate의 ActionQueue는 정해진 순서로 SQL을 실행해 배칭을 자동 적용하지만, 고정 순서에는 컬렉션을 비우고 새 행을 넣을 때 INSERT가 DELETE보다 먼저 실행돼 유니크 위반이 나는 함정이 있다. 그래서 유니크 키 값을 비우는 변경을 그 값을 차지하는 변경보다 먼저 실행한다.
- 순환(두 행이 유니크 값을 맞바꾸는 경우 등)은 에러로 보고하고 `DEFERRABLE INITIALLY DEFERRED` 제약을 안내한다.
- 겹침 처리: 집합 갱신이 `version`을 올리므로, 같은 행의 엔티티 갱신과 겹치면 재시도하지 않는 `IntraUsecaseConflict`(프로그래밍 오류)로 보고한다.

**합성: 단계는 `chain`으로만**
- 결정: 단계를 잇는 방법은 `with chain(order, wallet) as (c, order, wallet):` 하나다. 돌려받는 값은 chain의 최신 상태를 가리키는 뷰이고, 같은 이름으로 다시 묶어 원본을 가린다. `+`는 한 단계 안에서만 쓰고, 단계 호출 결과(`StepResult`)에는 `+`가 없어 단계끼리 `+`는 타입 에러다. chain 전에 만든 별칭은 이동 표시로 막는다(`MovedSnapshotAccess`). 블록을 벗어난 뷰는 읽기만 허용하고 `.set`은 `ChainClosed`다.
- 변천:
  1. `+`로 합치고 `order.apply(changes)`로 수동 연결: 깜빡하면 조용히 이전 값을 읽는다. 기각.
  2. 자동 연결을 옵션으로: 같은 코드가 설정에 따라 다른 의미가 된다. 기각.
  3. `+`(읽기 추적으로 충돌 감지) + `chain`: `charge(wallet, order.total)`처럼 값을 인자로 넘기면 읽기가 바깥 스코프에서 일어나 추적되지 않는다. 감지로는 완전히 막을 수 없어 기각.
  4. `chain(order=order)` 키워드 + `c.order`: 키워드 이름을 속성으로 만드는 건 타입으로 표현할 수 없어 `c.order`가 `Any`가 된다. 기각.
  5. **현재안**: 위치 인자 + TypeVarTuple로 타입을 붙이고, 같은 이름 재바인딩으로 원본 참조를 구조적으로 가린다. 남는 별칭 실수는 이동 표시가 정확히 잡는다.
- 블록 밖에서 쓰기를 막는 이유: 그 변경은 `c.changes`에 들어가지 않고 조용히 사라진다. 읽기는 해가 없어 허용한다.

**왕복 2회**
- 결정: 로드 배치 1회(BEGIN, 실행 ID 선점, 로드 1단계) + 커밋 배치 1회(쓰기, 프로젝션, outbox, 결과 기록, xid 조회, COMMIT, LSN 조회). `Load.after`가 있을 때만 로드 단계가 늘어난다.
- 근거: libpq 파이프라인은 앞 문장이 실패하면 뒤 문장을 실행하지 않으므로 COMMIT을 같은 배치에 넣어도 안전하다. 넓어지는 결과 불명 구간은 실행 ID가 덮는다. shield는 커밋 배치 전체에 걸린다.

**실행 ID: 멱등성과 커밋 결과 판정을 하나로**
- 결정: 모든 `app.run`에 실행 ID를 붙인다(호출자의 멱등 키, 없으면 자동 uuid7). 첫 문장에서 `run_claim`에 **조회 없이 INSERT**하고, 호출자 키인 경우 커밋 배치에서 결과를 `run_result`에 INSERT한다. 결과를 모르면 같은 실행 ID로 다시 실행한다: 커밋됐으면 23505 → 저장된 결과(호출자 키) 또는 실행기 메모리의 결과(자동 ID), 진행 중이면 유니크 키에서 대기, 롤백·유실됐으면 그대로 실행.
- 변천:
  1. 커밋 전에 xid를 받아 두고, 끊기면 `pg_xact_status(xid)`로 판정: 페일오버 시 복제되지 않은 xid가 새 프라이머리에서 다른 트랜잭션에 재사용될 수 있어, 남의 커밋을 내 성공으로 읽을 위험이 있었다. 타임라인 ID를 같이 확인하는 보완도 관리형 서비스(Aurora 등)에서 같은 의미인지 불분명했다.
  2. **현재안**: 실행 ID 하나로 멱등성과 커밋 판정을 처리한다. 이미 설계한 "같은 키 동시 요청" 경로를 그대로 쓰므로 새 장치가 없고, xid 판정과 페일오버 걱정이 사라진다.
- 조회 없이 INSERT하는 이유: ① 더블 클릭의 두 번째 요청이 업무 로직을 먼저 실행하면 이미 PAID인 주문을 보고 `AlreadyPaid`를 내버린다. 중복 확인은 업무 로직보다 앞에 있어야 한다. ② "조회해서 없으면 INSERT"는 아래 내부 테이블 규칙에 걸린다.
- 결과를 `run_claim`에 UPDATE하지 않고 별도 테이블에 INSERT하는 이유: UPDATE는 행을 찾으려고 인덱스를 읽어 같은 거짓 충돌을 다시 만든다.
- 비용: 커맨드마다 INSERT 한 줄(호출자 키면 두 줄)과 기간별 정리. 호출자 키 실행의 `returning` 값은 직렬화 가능해야 한다. 재생으로 얻은 토큰의 LSN은 새로 조회한다.

**내부 추가 전용 테이블 규칙**
- 결정: `run_claim`, `run_result`, outbox 로그, 작업 테이블, 소비자 체크포인트 같은 내부 테이블은 **SERIALIZABLE 트랜잭션 안에서 읽지 않는다.** SERIALIZABLE 트랜잭션이 이 테이블에 하는 일은 INSERT뿐이고, 읽기는 별도 READ COMMITTED 트랜잭션에서 한다. 갱신은 SERIALIZABLE 밖에서만 한다: 소비자 체크포인트(REPEATABLE READ)와 작업 리스(짧은 READ COMMITTED 트랜잭션). `run_claim`, `run_result`, outbox 로그는 어디서도 갱신하지 않는다.
- 근거: PostgreSQL의 SERIALIZABLE은 B-tree 리프 페이지 단위로 읽기 잠금을 건다. uuid7·시퀀스처럼 커지는 키는 모든 INSERT가 맨 오른쪽 리프 페이지에 몰린다. 그 페이지를 읽는 트랜잭션들은 서로의 읽기를 무효로 만드는 순환을 이루고, SSI가 이를 직렬화 실패로 끊는다. 결과적으로 서로 무관한 모든 커맨드가 재시도된다. 테이블이 작은 초기에는 테이블 단위 잠금이 걸려 더 나쁘다.
- 적용: 실행 결과 기록(UPDATE 대신 INSERT), 작업 완료 기록·펜싱(작업 ID를 실행 ID로 쓴 `run_claim` INSERT), 소비자 로그 읽기(별도 트랜잭션)가 모두 이 규칙에서 나왔다.
- 확인 필요: INSERT의 유니크 검사가 이런 읽기 잠금을 만들지 않는다는 가정은 동시성 테스트로 검증한다(§9).

**version의 역할**
- 결정: `version` 컬럼은 다음 네 가지에 쓴다.
  1. 요청 사이 낙관적 락: `Order.ref(id, expected_version=v)` → `VersionMismatch`. 두 요청을 잇는 트랜잭션이 없으니 DB가 감지할 수 없는 lost update를 막는다.
  2. 이벤트 순서: 같은 집계 안의 이벤트 순서 번호.
  3. 유스케이스 안의 겹침 감지: 집합 변경과 행 변경이 같은 행을 건드리는 경우.
  4. 다른 ORM과의 공존: DB 트리거로 올려 상대 ORM의 쓰기도 낙관적 락에 걸리게 한다.
- 바로잡은 점: 이전의 `StaleSnapshot`("REPEATABLE READ 모드의 버전 불일치")은 죽은 코드였다. REPEATABLE READ에서 동시에 갱신된 행을 고치면 PostgreSQL이 먼저 40001을 낸다. 그 자리를 요청 사이 락의 `VersionMismatch`가 대신한다.

**실행의 정체성: 질문마다 답이 따로 있다**

| 질문 | 기준 | 쓰는 곳 |
|---|---|---|
| 커밋됐는가 | 실행 ID | 멱등성, COMMIT 중 연결 끊김·페일오버 후 재실행 |
| 소비자가 어디까지 왔는가 | xid | outbox 워터마크, async 프로젝션 조회의 read-your-writes |
| 복제됐는가 | WAL LSN | 레플리카 라우팅 (replay LSN은 단조 증가라 앱에서 캐시해 비교) |
| 무엇이 먼저인가 | version | 같은 집계 안의 이벤트 순서 |

- 일관성 토큰은 (xid, LSN) 쌍이다. xid는 커밋 배치 안에서 조회한다. 재생으로 결과를 얻은 경우 LSN은 새로 조회하고, 자동 ID 재생으로 xid를 잃었으면 그 시점의 `pg_current_xact_id()`를 보수적인 상한으로 쓴다.

### 8.4 CQRS·이벤트

**프로젝션: inline 기본값, 대상·키 선언, 본문은 필드 연산만**
- 결정: `@projection(on=E, into=Target, key=E.field)`. 본문은 그 대상 행에 대한 필드 연산만 돌려준다. inline이면 키는 이벤트의 엔티티 ID 필드만 허용하고, 날짜·상수 같은 파생 키는 seal에서 거부한다(async로 돌리거나 `allow_hot_key="사유"`).
- 근거: 주 타깃은 브로커 없이 시작하는 작은 팀이라 강한 일관성이 기본이다. 그런데 SERIALIZABLE 기본값과 만나면 일별 매출 같은 전역 집계 행에 모든 결제가 몰린다. 키만 선언하고 본문에서 아무 키로나 upsert할 수 있으면 이 규칙을 우회할 수 있으므로, 대상과 키를 선언으로 올렸다.
- 이 규칙은 명백한 경우만 거른다. `store_id`·인기 상품 ID처럼 엔티티 ID도 뜨거울 수 있으므로 프로젝션별 재시도율 메트릭을 항상 둔다.

**이벤트의 집계와 순서**
- 결정: `@event(aggregate=lambda: E.order_id)`로 어느 집계의 이벤트인지만 선언하고, 순서 번호(집계 버전, 트랜잭션 안 순번)는 엔진이 커밋 때 채운다. 집합 변경의 `emit_each`는 `UPDATE … RETURNING id, version` 결과로 채운다.
- 근거: 이벤트에 `order_version=order.version + 1`을 손으로 쓰게 한 이전 안은 실수할 장소였다. chain에서 두 단계가 각각 이벤트를 내면 번호가 어긋나고(UPDATE는 한 번이라 DB는 +1), 집계 행을 안 고치고 이벤트만 내면 틀린 번호가 나간다.
- 집계 행을 고치지 않고 이벤트만 낼 때는 **버전을 올리는 것이 기본값**이다. 순서를 보장하려면 그 집계 행이 직렬화 지점이 돼야 하기 때문이다. 이 경우 집계는 자기 모듈의 엔티티여야 한다(다른 모듈의 행은 쓸 수 없으므로). 순서가 필요 없는 알림성 이벤트나 다른 모듈의 ID를 집계로 삼는 이벤트는 `ordered=False`로 선언한다.

**일관성 토큰 API**
- 결정: `result.token`은 불투명 문자열인 (xid, LSN) 쌍이다. LSN은 커밋 직후 `pg_current_wal_insert_lsn()`으로 얻는다. `query(..., after=token)`은 레플리카의 replay LSN이 토큰 LSN 이상이면 레플리카, 아니면 프라이머리를 쓴다. async 프로젝션 조회는 소비자 워터마크가 토큰 xid를 지났는지로 판단한다. 기본은 기다리지 않고 프라이머리로 폴백, `wait_ms` 옵션으로 대기 가능.
- WAL 위치는 쓰기 위치(`pg_current_wal_lsn()`)가 아니라 **삽입 위치**를 쓴다. `synchronous_commit=off`에서는 쓰기 위치가 커밋 레코드보다 뒤처질 수 있다.

**outbox 로그와 소비자 체크포인트**
- 결정: outbox는 **추가 전용 이벤트 로그**이고, 처리 상태는 소비자 쪽에 둔다. 각 행에 xid와 시퀀스를 기록하고, 소비자는 `xid < pg_snapshot_xmin(pg_current_snapshot())`인 행, 즉 확실히 끝난 트랜잭션의 이벤트만 읽는다. 로그 읽기는 별도 READ COMMITTED 트랜잭션에서 한다(내부 테이블 규칙).
- `(xid, seq)`는 처리 순서일 뿐 의미상 순서가 아니다. 같은 집계 안의 순서가 중요하면 이벤트의 순서 번호를 쓴다.
- 바로잡은 점: 이전 안은 "INSERT 전용"이라면서 리스 컬럼을 UPDATE했고, 시퀀스 워터마크는 늦게 커밋된 낮은 번호를 건너뛰었다. xid 워터마크는 진행 중인 트랜잭션이 끝나기 전에는 넘어가지 않는다.
- 트레이드오프: 오래 열린 쓰기 트랜잭션 하나가 xmin을 붙잡으면 모든 소비자가 그만큼 지연된다. 이 지연을 메트릭으로 노출한다.
- 로그가 진짜 추가 전용이라 Debezium Outbox Event Router의 컬럼 관례를 따를 수 있고, 처리량이 커지면 CDC로 전환한다. CDC는 폴링 지연이나 DB 부하가 측정된 문제가 됐을 때 도입하는 게 일반적 권고다.

**async 프로젝션 소비자**
- 결정: 프로젝션마다 직렬 소비자 하나. 효과와 체크포인트를 **REPEATABLE READ** 트랜잭션에 함께 커밋해 정확히 한 번 반영한다. 독성 메시지는 건너뛰지 않고 멈추고 알린다.
- 근거: 프로젝션 효과는 `.add` 같은 교환 가능한 필드 연산이고 체크포인트마다 소비자가 하나라 SERIALIZABLE이 필요 없다. SERIALIZABLE로 돌리면 체크포인트 테이블에서 소비자끼리 거짓 충돌이 난다. 건너뛰면 읽기 모델이 틀어진다.

**작업 처리: then과 @process의 2계층 파이프라인**
- 결정:
  - **로그 리더**: xid 워터마크로 빠짐없이 읽어 핸들러별 작업 테이블에 INSERT하고, 리더 체크포인트를 같은 트랜잭션에 기록한다.
  - **워커**: 짧은 READ COMMITTED 트랜잭션에서 `SKIP LOCKED`로 리스를 잡고, 외부 IO는 트랜잭션 밖에서 한다.
  - **디스패처**: 작업 ID를 실행 ID로 해서 핸들러가 돌려준 유스케이스를 실행한다. 첫 문장인 `run_claim` INSERT가 완료 기록이자 펜싱이다. 리스가 만료돼 두 워커가 같은 작업을 끝내면 늦은 쪽은 23505를 받고 아무것도 하지 않는다. 핸들러가 `None`을 돌려주면 `run_claim`만 커밋한다.
  - **순서**: 집계 키마다 가장 앞선 작업 하나만 처리 중일 수 있다.
  - **실패**: 일시적 오류는 백오프 재시도. 도메인 예외는 즉시 dead-letter가 기본이고, 예외 타입이 `retry_later=RetryLater(max_attempts, within)`를 선언했을 때만 나중에 재시도한다(상한을 넘으면 dead-letter). 맨 앞 작업이 dead-letter로 가면 그 키의 뒤 작업도 막는다. "막힌 키 수" 메트릭과 감사 기록을 남기는 재전송·건너뛰기 도구를 둔다.
  - **@process는 서술을 돌려준다.** `app.run`을 부르지 않는다. 외부 호출에는 프레임워크가 주는 `ctx.idempotency_key`를 쓴다. 멱등 키를 받지 않는 외부 API는 상태를 먼저 조회한 뒤 판단하도록 짠다.
- 변천:
  1. 소비자당 워커 하나 + 순서 체크포인트를 모든 소비자에 적용: 느린 외부 IO가 파티션 수만큼으로 처리량을 묶고, 독성 메시지 하나가 뒤를 전부 막았다.
  2. 핸들러가 `app.run`을 부르고 (이벤트, 핸들러, 유스케이스)로 멱등 키 구성: 첫 전달에서 승인 유스케이스가 커밋된 뒤 재전달 때 외부 API가 "이미 승인됨" 오류를 주면, 키가 다른 취소 유스케이스가 실행되는 구멍이 있었다. 호출 순번을 키에 넣는 보완은 배포나 분기 변화에 깨졌다.
  3. **현재안**: 핸들러는 서술을 돌려주고 디스패처가 완료 기록과 한 트랜잭션에 커밋한다. 커밋 뒤에는 재전달이 없으므로 DB 쪽 키 설계가 필요 없다. 남는 구간(외부 IO 후, 커밋 전 장애)은 외부 멱등 키가 막는다.
- 근거: 리스를 쥔 채 외부 IO를 기다리면 그 트랜잭션이 xid를 가진 채 열려 있어 로그 리더 전체가 멈춘다. 완료 기록을 `WHERE lease_token = $n` UPDATE로 하면 SERIALIZABLE 유스케이스 트랜잭션 안에서 작업 테이블을 읽게 되어 내부 테이블 규칙을 어긴다. 그래서 펜싱을 유니크 INSERT로 했다. 처음에는 별도 `job_done` 테이블을 두었지만, 디스패처가 작업 ID를 실행 ID로 쓰면 `run_claim`과 같은 일을 하는 유니크 INSERT가 두 번이 되므로 하나로 합쳤다.
- `then` 유스케이스는 유스케이스 의미론 그대로 SERIALIZABLE로 실행된다.

**배치 체크포인트 저장소**
- 결정: 같은 DB의 `platina_batch_checkpoint` 테이블. 각 청크 커밋과 같은 트랜잭션에서 커서를 갱신해, 재시작 시 정확히 다음 청크부터 이어간다.

### 8.5 도구·생태계

**코드젠의 스키마 출처**
- 결정: 엔티티 테이블은 Python 엔티티 정의가 정본. TypedSQL 타입 추론은 마이그레이션을 적용한 임시 PostgreSQL에서 prepared statement describe로 수행. **생성 코드는 저장소에 커밋**하고 CI에서는 `platina gen --check`로 최신성만 검사.
- 근거: Prisma TypedSQL은 타입 생성 시 실행 중인 DB 연결이 필요하고, 무상태 CI에서 이 제약이 불편하다는 요구가 반복된다. sqlc도 정적 분석만으로는 복잡한 쿼리의 타입 추론에 한계가 있어 DB 기반 분석을 추가했다.

**스키마 도구: SQLAlchemy Core + Alembic 혼합 (선택 extra)**
- 결정: 쿼리 컴파일러와 실행 엔진은 독립으로 유지하고, **DDL 생성·카탈로그 리플렉션·마이그레이션은 SQLAlchemy Core와 Alembic에 맡긴다.** 엔티티 레지스트리를 SQLAlchemy `MetaData`로 변환해 Alembic autogenerate를 쓴다. 이 기능은 `platina migrate`·`pull`·drift 검사 때만 필요하므로 `platina[migrate]` 선택 extra로 두어, 런타임 코어는 SQLAlchemy에 의존하지 않는다.
- 변천: 처음에는 "Alembic은 SQLAlchemy 메타데이터에 묶여 독립 ORM에 맞지 않는다"며 마이그레이션 도구를 자체 구현하기로 했다. 그런데 Core를 쓰지 않는 근거(§8.1)가 틀렸고, Core가 실제로 아껴 주는 작업이 쿼리 컴파일이 아니라 DDL·리플렉션·마이그레이션이라는 점이 드러나 결정을 뒤집었다. MySQL을 붙일 때도 이쪽 작업을 공짜로 얻는다.
- 위험: 변환의 충실도. Alembic autogenerate가 약한 지점이 이 설계의 기능과 겹친다. ① `renamed_from` 힌트(autogenerate는 rename을 감지하지 못함 → `process_revision_directives` 훅으로 drop+add를 rename으로 바꾸는 방안), ② 람다로 선언한 `Check`, ③ `version` 트리거(Alembic은 트리거를 다루지 않음 → 서드파티 PG 객체 지원 검토), ④ 표현식·부분 인덱스, ⑤ 프레임워크 내부 테이블(특히 파티션). 이 다섯 가지가 왕복되는지가 스파이크 항목이다(§9).
- 근거(참고): Atlas는 코어가 Apache 2.0이지만 오픈코어이고 2025년 10월 v0.38에서 마이그레이션 린트를 유료 등급으로 옮겼다. sqldef는 SQL 파일 하나로 스키마를 관리하지만 Go 바이너리라 `pip install` 한 번으로 끝나는 경험을 깨뜨린다.

**Pydantic 연동**
- 결정: 코어는 Pydantic에 의존하지 않는다. 엔티티와 DTO는 자체 불변 클래스(slots)와 frozen dataclass. `platina-pydantic` 플러그인이 프로젝션·TypedSQL 결과에서 API 응답용 Pydantic 모델을 생성.

**Django 어댑터: 만들지 않음**
- 결정: 로드 계획을 Django QuerySet으로 컴파일하는 어댑터는 만들지 않는다. 공존은 `platina pull`(DB 카탈로그 → 엔티티) + `version` 트리거로 해결하며, Django·SQLAlchemy를 구분하지 않는다.

### 8.6 비동기·런타임

**최소 Python: 3.14**
- 근거: psycopg 3.3이 Python 3.14의 t-string을 이용한 안전한 쿼리 작성을 지원한다. 3.14부터 지연 평가 어노테이션이 기본이다. free-threaded 빌드는 PEP 779 승인으로 3.14에서 "실험적" 딱지를 뗐다. 3.15가 2026년 10월 9일 출시됐으므로, 2027년에 나올 신규 라이브러리가 3.14+를 요구하는 것은 무리가 없다.

**드라이버: psycopg 3.3+ 단일**
- 근거: sync·async 인터페이스를 모두 제공하고(sync 실행기를 1급으로 유지하려면 필수), 파이프라인 모드·COPY·t-string을 지원한다. asyncpg는 빠르지만 async 전용이라 sync 실행기를 만들 수 없다.

**MySQL: 지원 계획 있음, 시점 미정**
- 결정: 컴파일러의 방언 계층 위에 MySQL(및 MariaDB) 방언을 추가할 계획이다. 시점은 PostgreSQL 구현이 안정화된 뒤 정한다.
- 현실적 제약: MySQL은 여전히 `RETURNING`을 지원하지 않고, 지원 요청 버그가 8.x·9.x 대상으로 열려 있다. 데이터 수정 CTE도 없다. 반면 MariaDB는 10.5부터 `INSERT … RETURNING`을 지원하고, 13.0 GA에서 `UPDATE … RETURNING`까지 추가했다.
- 그래서 MySQL은 **기능 축소 모드**로 지원한다.

| 기능 | PostgreSQL | MySQL에서의 대체 |
|---|---|---|
| 집합 변경 + outbox 한 문장 | 데이터 수정 CTE | `SELECT … FOR UPDATE`로 대상 ID 확보 → `UPDATE` → outbox `INSERT` (왕복 3회) |
| 청크 갱신 충돌 행 식별 | `UPDATE … RETURNING` | 선행 `SELECT … FOR UPDATE` 후 비교 |
| 로드 계획 한 번에 전송 | libpq 파이프라인 | 순차 실행 (또는 multi-statement, 드라이버에 따라) |
| 일관성 토큰 | WAL LSN | GTID |
| 기본 SERIALIZABLE | SSI (낙관적, 40001 재시도) | InnoDB는 잠금 기반이라 특성이 다름 → MySQL 기본값은 별도 결정 |
| 재귀 로드 | `WITH RECURSIVE … CYCLE` | `WITH RECURSIVE` (8.0+), 순환 감지는 경로 컬럼으로 직접 |

- 아직 정하지 않은 것: MySQL 드라이버(sync·async 둘 다 필요), MySQL에서의 기본 격리 수준, MariaDB를 MySQL과 같은 방언으로 묶을지 분리할지.

**trio: 미지원, 자체 wire protocol: 하지 않음**
- 근거: psycopg 공식 문서는 asyncio 인터페이스와 gevent 지원을 다룬다. anyio 지원 PR이 제안된 적은 있지만, 메인테이너는 후원 없이는 Trio 지원 작업을 하지 않겠다고 밝혔다. trio 전용 드라이버는 triopg(유지보수 중단 공지)와 순수 Python 구현인 pgtrio 정도라 기반으로 삼기 어렵다.
- 그래도 anyio API로 작성하는 이유: cancel scope와 shield라는 취소 의미론 때문. 백엔드는 asyncio로 고정.

**free-threaded Python**
- 결정: 코어(sans-IO, 불변 스냅샷)는 3.14t를 CI 대상에 포함. sync 실행기 + 스레드 조합의 공식 지원은 psycopg-binary가 free-threaded 휠을 내는 시점으로 미룬다.
- 근거: 2026-11-24 PyPI 확인 결과 psycopg-binary 3.3.9는 cp310~cp315 휠만 있고 free-threaded(`cp3xxt`) 휠은 없다. asyncpg 0.32.0은 cp314t 휠을 제공한다.

---

## 9. 실험 계획 (프로토타입 전에 확인할 것)

다섯 차례의 리뷰를 거치며 지적이 점점 구현 세부로 내려왔다. 남은 질문은 문서로는 답이 나오지 않고 실험으로만 답이 나온다. 특히 SSI 상호작용은 리뷰어와 설계자 모두 문서 위에서 같은 종류의 실수를 반복했다. 그래서 다음 네 실험을 구현보다 먼저 한다.

### 9.1 타입 스텁 스파이크 (최우선)
§4 문법 전체가 여기에 달려 있다. 구현 없이 스텁만으로 §11.8의 통과·실패 파일을 pyright와 mypy에 돌린다. 결과: [스파이크 0001](../spikes/0001-type-surface.md)(독립적으로 재현함, 나중에 돌린 변성 프로브는 제외), ADR-0003, ADR-0004.
- [x] `Col[T]`: 클래스 접근 `Column[T]`, 인스턴스 접근 `T` - 성립. 클래스 접근은 이제 `Column[Owner, T]`(ADR-0004)
- [x] 생성자: `__set__(self, instance: Never, value: T)`로 생성자 파라미터 타입은 얻고 대입은 막히는가. 안 되면 생성된 모듈의 타입 붙은 생성 함수로 - `Entity` 기반 클래스 위에서 1단계로 성립. 생성은 `Order(...)`(ADR-0003)
- [x] `with chain(a, b) as (c, a, b)`: TypeVarTuple로 각 이름의 타입이 유지되는가 - 성립
- [x] `bind`: ParamSpec으로 이름·타입 검사, `INJECTED` 기본값 생략 - 성립(`INJECTED` 기본값에 대한 seal 규칙은 미결, #48)
- [x] 임베디드 경로(`Order.total.amount`)와 값 객체 연산(`Wallet.balance.add(Decimal)`) - 쓰인 그대로는 불가. 소유자 타입 컬럼과 `Order.total.path(Money.amount)`는 성립하고, 증감은 경로를 거친다(ADR-0004)
- [x] `StepResult`끼리 `+`가 에러인가, Finder 인자 타입 - 성립

### 9.2 SSI 동시성 실험
실제 PostgreSQL에서 동시 실행으로 거짓 충돌(직렬화 실패) 비율을 잰다.
- [ ] 실행 ID `run_claim` INSERT(uuid7)만으로는 거짓 충돌이 생기지 않는가 (INSERT의 유니크 검사가 읽기 잠금을 만들지 않는다는 가정)
- [ ] 대조군: "조회 후 INSERT", "INSERT 후 UPDATE" 방식에서 실제로 충돌이 나는가 (규칙의 근거 확인)
- [ ] 작업 ID를 실행 ID로 쓴 `run_claim` 펜싱(동시 완료 시 대기·23505 거동), inline 프로젝션의 재시도율
- [ ] 테이블이 작은 초기 상태(테이블 단위 잠금)에서의 거동
- [ ] 대표 워크로드에서 SERIALIZABLE 기본값의 처리량·재시도율 (REPEATABLE READ + version 대비)

### 9.3 MetaData → Alembic 왕복
엔티티 레지스트리를 SQLAlchemy `MetaData`로 변환해 Alembic autogenerate가 다음을 손실 없이 왕복하는지 본다.
- [ ] `renamed_from` 힌트 (`process_revision_directives`로 drop+add → rename 변환)
- [ ] 람다로 선언한 `Check`
- [ ] `version` 트리거
- [ ] 표현식·부분 인덱스
- [ ] 프레임워크 내부 테이블(특히 파티션)

### 9.4 실제 유스케이스 10개를 이 문법으로 옮기기
각각 설계의 다른 부분을 시험하도록 골랐다. 종이에 옮겨지지 않는 게 나오면 문법을 고친다.

| # | 유스케이스 | 시험하는 부분 |
|---|---|---|
| 1 | 결제 | 멱등 키, 실행 ID |
| 2 | 환불 | 의존 로드(`Load.when`/`after`) |
| 3 | 쿠폰 적용 후 결제 | `chain` |
| 4 | 재고 예약 | 핫 로우, 비관적 락 프로필 |
| 5 | 좌석 예약 | write skew, SERIALIZABLE |
| 6 | 주문 병합 | 같은 타입 파라미터 둘, `Load.after` |
| 7 | 미결제 주문 일괄 만료 | 집합 변경, `emit_each` 순서 번호 |
| 8 | 계좌 이체 | 원장, 교환 가능한 증감 |
| 9 | 프로필 편집 | `expected_version`, `owned` 자식 |
| 10 | 결제 승인 알림 | `@process`, 작업 파이프라인, 외부 멱등 키 |

### 9.5 그 밖의 측정
- [ ] 파이프라인 효과: 로드 단계를 한 왕복에 보낼 때와 순차 실행 대비 지연 (로컬 / 리전 간)
- [ ] 불변 스냅샷 + `.set` 연산, 이동 표시·읽기 추적의 오버헤드
- [ ] `Load.after`가 실제로 얼마나 자주 필요하고 왕복을 몇 단계 늘리는지
- [ ] `.set(Column.to(...))`의 장황함이 실사용에서 수용 가능한지
- [ ] 실행 ID·작업 테이블의 쓰기 증폭과 정리 비용
- [ ] seal 시간 (유스케이스 수백 개 규모)

### 9.6 1차 범위 제안 (미결정)
범위가 넓다는 지적을 반영한 제안이다. 실험 결과를 보고 확정한다.
- **1차**: 순수 유스케이스와 실행 엔진, PostgreSQL 방언, 실행 ID, inline 프로젝션, Query 경로(TypedSQL), 스키마 도구(선택 extra)
- **2차**: async 프로젝션, `then`·`@process`와 작업 파이프라인, 배치 유스케이스
- **이후**: MySQL·MariaDB 방언, saga 헬퍼, free-threaded 공식 지원

### 9.7 기타
- [x] 이름 확정: Platina (§8.1)

---

## 10. 내부 아키텍처 (코드베이스 설계)

### 10.1 원칙: ORM 자신도 철학을 따른다

사용자에게 요구하는 규칙을 Platina의 코드베이스에도 똑같이 적용한다.

> **IO 없는 코어(functional core)와 IO만 하는 얇은 껍데기(imperative shell).**

- **코어**: 스키마 레지스트리, 표현식 AST, 로드 계획, ChangeSet, 커밋 플래너, SQL 컴파일러, 실행 엔진. 소켓·드라이버·이벤트 루프를 import하지 않는다.
- **껍데기**: sync/async 실행기, psycopg 드라이버 어댑터, CLI, 프레임워크 통합.
- 이 경계는 리뷰가 아니라 **import-linter 계약으로 CI에서 강제**한다(§10.4). 사용자에게 권하는 도구를 우리가 먼저 쓴다.

### 10.2 참고한 내부 구조

| 출처 | 내부 구조 | 가져오는 것 | 피하는 것 |
|---|---|---|---|
| psycopg 3 | 네트워크 코드를 기다려야 할 때 yield하는 제너레이터로 작성하고, sync/async 차이는 `wait()` 함수에만 둔다. 상위 API의 sync 코드는 async 코드의 AST에서 자동 생성하고, CI에서 어긋남을 검사한다 | 실행 엔진을 **제너레이터 기반 상태 기계**로. 얇은 공개 API 층은 async→sync 자동 생성 | |
| SQLAlchemy | 1.4부터 SQL 컴파일 결과를 캐시 키로 캐싱. 캐시 키를 만들지 못하는 구성 요소는 경고가 나고 성능이 크게 떨어진다 | 컴파일 캐시 | 캐시 참여를 구성 요소별로 opt-in해야 하는 구조. 우리 AST는 **불변이라 구조적 해시가 기본으로** 생긴다 |
| SQLAlchemy | 서드파티 방언용 "dialect compliance suite"와, 방언별 지원 여부를 표시하는 `Requirements` 클래스 | 방언 **능력(capability) 플래그** + 호환성 테스트 스위트 (MySQL 방언 추가 시 필수 관문) | |
| Hibernate | ActionQueue가 쓰기 지연 DML을 모아 두었다가 flush 때 정해진 순서로 실행, 덕분에 배칭이 자동 적용됨 | 커밋 플래너가 변경을 모아 **정렬 + 배치**로 실행 | 고정 순서 (컬렉션 교체 시 유니크 위반). 우리는 의존성 그래프 |
| Ecto | Adapter behaviour가 어댑터의 최소 API를 정의하고, 조회 등은 `Ecto.Adapter.Queryable` 같은 별도 behaviour로 나뉜다 | 드라이버·방언 인터페이스를 **능력별 작은 Protocol**로 분리 | |
| Prisma | (설계 노트 §2) 사이드카 쿼리 엔진 → 순수 TS로 이전 | | 별도 엔진 프로세스. 우리는 전부 in-process |
| Django | 모델 메서드가 바로 DB를 치고, 시그널이 전역 부수효과로 연결됨 | | 전역 시그널. 확장은 명시적으로 등록한 플러그인만 |

### 10.3 패키지 구조

```
platina/
├── core/                    # ── IO 없음 (import-linter로 강제) ──
│   ├── schema/              # Entity·@value 메타데이터, 타입 매핑, 레지스트리, seal 검증
│   ├── expr/                # 불변 표현식 AST (frozen dataclass + slots), 구조적 해시
│   ├── snapshot/            # 불변 스냅샷, ref 자리표시자, 이동 표시, 필드 디스크립터(Column[Owner, T] / T)
│   ├── changes/             # 필드 연산(.to/.add/items.add…), 단계 내 +, chain, 최종 차이 계산
│   ├── plan/                # 로드 계획(Load/Profile/when/after/recursive), 로드 단계 DAG
│   ├── planner/             # 커밋 플래너: 의존성 그래프 → 위상 정렬 → 배치
│   ├── engine/              # 실행 엔진: Command를 yield하는 상태 기계 (재시도·백오프 포함)
│   └── errors.py            # 예외 계층 (구조화된 필드 포함)
├── sql/                     # ── IO 없음 ──
│   ├── compiler/            # AST → SQL 공통 부분, 컴파일 캐시
│   └── dialects/
│       ├── base.py          # DialectCapabilities, 전략 선택
│       └── postgresql/      # PG 방언 (MySQL은 나중에 여기 형제로)
├── app/                     # ── 껍데기 ── App, seal 조립, run/query (ADR-0001)
├── runners/                 # ── 껍데기 ──
│   ├── async_.py            # anyio + psycopg AsyncConnection (원본)
│   └── sync_.py             # async_.py에서 자동 생성 (직접 수정 금지)
├── drivers/psycopg/         # 연결 풀, 파이프라인, COPY, 타입 어댑터, SQLSTATE → 예외 매핑
├── outbox/                  # 이벤트 로그, 소비자 체크포인트(xid 워터마크), 프로젝션·process·then 디스패처
├── migrate/                 # [extra] 레지스트리 → SQLAlchemy MetaData 변환, Alembic 연동, drift 검사
├── codegen/                 # TypedSQL 타입 추론, platina pull, import-linter 계약 생성
├── testing/                 # 사용자용 테스트 키트 + 방언 호환성 스위트
├── integrations/fastapi/
└── cli/                     # platina check / gen / migrate / pull / contracts
```

### 10.4 레이어 규칙

```toml
# pyproject.toml — Platina 자체 저장소의 계약
[[tool.importlinter.contracts]]
name = "platina layers: shell -> core only"
type = "layers"
containers = ["platina"]
exhaustive = true            # platina의 모든 직속 패키지가 레이어에 있어야 함
layers = [
    "cli | integrations | testing",
    "app",                   # App, seal 조립 (ADR-0001)
    "runners | outbox | migrate | codegen",
    "drivers",
    "sql",
    "core",
]
```

- import-linter는 우리 패키지 사이의 레이어만 검사한다. 영역마다 어떤 *외부* 모듈을 쓸 수 있는지는 `tools/guards/archlint.py`가 강제한다: 코어(`core`, `sql`)는 허용 목록에 있는 표준 라이브러리 모듈만 import하고(그래서 psycopg, anyio, asyncio, socket, threading, time, random, os, logging, sqlalchemy, alembic 등은 쓸 수 없다), `async`가 없으며, 시계나 난수 ID 함수를 부르지 않는다. psycopg는 `drivers`에서만, SQLAlchemy와 Alembic은 `migrate`(선택 extra)에서만 import한다.
- `time`까지 금지하는 이유: 백오프 대기조차 코어가 직접 하지 않고 `Sleep` 명령으로 요청한다. 덕분에 엔진 테스트가 실제 시간을 쓰지 않는다. 시간이나 우연에 따라 달라지는 값은 코어 안에서 만들지 않는다. 시계는 `Now` 파라미터로(§4.5), 지터용 난수는 엔진 인자로, 새 ID는 주입된 ID 소스에서 받는다(ADR-0002).

### 10.5 실행 엔진: sans-IO 상태 기계

엔진은 IO가 필요할 때마다 **명령(Command)을 yield**하고, 결과(Reply)를 받아 진행하는 제너레이터다. 실행기는 명령을 실제 IO로 바꿔 주는 루프일 뿐이다.

```python
# core/engine/commands.py
@dataclass(frozen=True, slots=True)
class Begin:    isolation: Isolation; timeout: str | None
class Pipeline: statements: tuple[CompiledSQL, ...]      # 한 왕복으로 보낼 문장들
class Copy:     table: str; columns: tuple[str, ...]; rows: Iterable[tuple]
class CommitBatch: statements: tuple[CompiledSQL, ...]  # 쓰기·프로젝션·outbox·결과 기록·COMMIT·LSN 조회 (한 왕복)
class StoredResult: run_id: RunId                        # 별도 READ COMMITTED 트랜잭션에서 run_result 조회
class FreshLsn: ...                                      # pg_current_wal_insert_lsn() 조회
class Rollback: ...
class Sleep:    seconds: float                           # 재시도 백오프

# core/engine/run.py  (IO 없음)
def run_usecase(uc: Usecase, args: Bound, policy: RetryPolicy, d: Dialect
               ) -> Generator[Command, Reply, RunResult]:
    pending: RunResult | None = None                        # 커밋 전에 계산해 둔 결과 (시도를 넘어 유지)
    for attempt in policy.attempts():
        try:
            snapshots = {}
            for i, stage in enumerate(uc.plan.stages):        # 단계 수는 seal에서 확정
                head = (begin(uc.isolation, uc.timeout), claim(run_id)) if i == 0 else ()
                rows = yield Pipeline(head + stage.compile(d, args, snapshots))   # 왕복 1: BEGIN + 실행 ID 선점 + 로드
                snapshots |= stage.materialize(rows)          # Load.after 함수도 여기서 실행(순수)
            changes = uc.invoke(snapshots)                    # 사용자 유스케이스: 평범한 순수 함수
            pending = RunResult.from_changes(changes)
            reply = yield CommitBatch(commit_plan(changes, d, run_id))   # 왕복 2: 쓰기 … COMMIT, LSN
            return pending.committed(reply)
        except AlreadyClaimed:                              # run_claim 23505: 같은 실행 ID가 이미 커밋됨
            yield Rollback()
            match run_id.kind:
                case "caller":                              # 호출자 키: 저장된 결과
                    return (yield StoredResult(run_id))     # 별도 READ COMMITTED로 run_result 조회
                case "auto":                                # 자동 ID: 이 실행기의 직전 시도가 커밋된 것
                    return pending.committed_with((yield FreshLsn()))   # 메모리의 결과 + 새 LSN
                case "job":                                 # 작업 ID: 다른 워커가 이미 완료
                    return RunResult.already_done(run_id)
        except RetryableError as e:                         # 실행기가 gen.throw()로 넣어 준 DB 오류
            yield Rollback()
            yield Sleep(policy.backoff(attempt, e))
        except CommitUnknown:                               # 커밋 배치 도중 연결 끊김
            continue                                        # 같은 run_id로 재실행 → 커밋됐으면 AlreadyClaimed
    raise RetryExhausted(...)
```

```python
# runners/async_.py  (껍데기: 명령을 IO로 바꾸는 루프)
async def drive_async(gen, conn):
    reply = None
    while True:
        try:
            cmd = gen.send(reply) if not isinstance(reply, BaseException) else gen.throw(reply)
        except StopIteration as stop:
            return stop.value
        try:
            if isinstance(cmd, (CommitBatch, Rollback)):
                with anyio.CancelScope(shield=True):          # 커밋 배치·롤백은 취소로 끊기지 않음
                    reply = await execute(conn, cmd)
            elif isinstance(cmd, Sleep):
                reply = await anyio.sleep(cmd.seconds)
            else:
                reply = await execute(conn, cmd)
        except psycopg.Error as e:
            reply = map_sqlstate(e)                            # 40001 → RetryableError 등
```

- **sync/async 의미가 100% 같다.** 둘 다 같은 엔진 제너레이터를 돌린다. 다른 건 루프의 `await`와 shield뿐이다.
- **취소 지점이 명시적이다.** 엔진이 yield하는 곳만이 취소될 수 있는 곳이다.
- **엔진을 DB 없이 테스트할 수 있다.** 미리 준비한 응답을 `send`하면 된다(§11.4).
- 실행기 코드 자체는 psycopg와 같은 방식으로 `async_.py`를 원본으로 두고 `sync_.py`를 AST 변환으로 생성한다. 사람이 두 벌을 관리하지 않는다.

### 10.6 SQL 컴파일러: 불변 AST + 방언 능력

- **AST 노드는 `frozen=True, slots=True` dataclass.** 구조적 동등성과 해시가 기본이라, 바인드 값을 뺀 AST 자체가 컴파일 캐시 키가 된다. 사용자 정의 표현식도 노드 규칙만 지키면 자동으로 캐시에 참여한다.
- **컴파일은 방언별 `match` 디스패치.** `PostgresCompiler`가 공통 `Compiler`를 상속하고, 다른 노드만 재정의한다.
- **방언 차이는 if문이 아니라 전략으로.**

```python
@dataclass(frozen=True)
class DialectCapabilities:
    update_returning: bool          # PG ✓, MySQL ✗, MariaDB 13+ ✓
    data_modifying_cte: bool        # PG ✓, MySQL ✗
    pipeline: bool                  # PG(libpq 14+) ✓
    copy: bool
    recursive_cycle_clause: bool    # PG 14+ ✓
    ssi: bool                       # 낙관적 SERIALIZABLE

# 플래너는 능력을 보고 전략을 고른다
set_update_strategy = CteWithOutbox if caps.data_modifying_cte else LockSelectUpdateInsert
```

MySQL 지원은 이 전략 몇 개와 방언 컴파일러를 추가하는 일이 된다. 코어 곳곳에 `if dialect == "mysql"`이 퍼지지 않는다.

### 10.7 커밋 플래너 (Hibernate ActionQueue에 해당)

```
ChangeSet
  → RowOp 목록 (Insert / Update / Delete / LinkAdd / LinkRemove)
  → 의존성 그래프
       · FK: 부모 INSERT → 자식 INSERT,  자식 DELETE → 부모 DELETE
       · 유니크 키: 값을 비우는 연산(DELETE, 값 변경) → 같은 값을 차지하는 연산
  → 위상 정렬 (동률이면 테이블·연산·컬럼 집합으로 묶이게 정렬)
  → 배치 묶기: multi-row INSERT / unnest UPDATE / DELETE … WHERE id = ANY($1)
  → Pipeline 명령 (COPY는 별도 명령)
```

- 순환이 생기면 `CommitCycle` 에러로 어떤 행·제약 때문인지 보고하고, `DEFERRABLE INITIALLY DEFERRED` 제약을 안내한다.
- 플래너는 순수 함수라 속성 기반 테스트의 주 대상이다(§11.3).

### 10.8 스냅샷, ref, 이동 표시

- 엔티티 스냅샷은 seal 시점에 엔티티마다 생성하는 **slots 클래스**(내부 값은 튜플)다. 엔티티는 `Entity`를 상속하는데(ADR-0003) `__init_subclass__`는 `__slots__`를 추가할 수 없으므로, slots 클래스는 `Entity` 메타클래스가 만들거나 별도 스냅샷 클래스로 만든다. 필드 접근은 디스크립터를 거치고, 클래스에서 접근하면 `Column[Owner, T]`, 인스턴스에서 접근하면 `T`를 돌려준다.
- **ref**는 같은 클래스의 "로드되지 않은" 인스턴스다. 식별 정보(PK나 Finder 키)만 갖고, 필드를 읽으면 `UnloadedReference`를 낸다. 실행기가 로드 계획을 만들 때 ref를 수집한다.
- **chain 뷰**: `chain(order, wallet)`이 돌려주는 값은 chain의 최신 상태를 가리키는 뷰 객체다(타입상 원래 엔티티). `c.run`에 넘길 때 그 시점의 불변 스냅샷으로 바뀌고, 블록을 벗어나면 최종 상태로 고정되며 `.set`은 `ChainClosed`를 낸다.
- **이동 표시**: `chain(order, ...)`은 현재 단계의 `contextvars` 기록에 "이 스냅샷 객체는 이동됨"을 남긴다. 같은 이름 재바인딩으로 대부분의 원본 참조는 구조적으로 사라지고, 이 표시는 chain 전에 만든 별칭을 막는다. 디스크립터가 필드를 읽을 때와 `__eq__`·`__hash__`가 실행될 때 이 표시를 확인해 `MovedSnapshotAccess`를 낸다. 표시는 단계 스코프별이라, 같은 스냅샷을 다른 코루틴·스레드가 쓰는 데는 영향이 없다.
- **읽기 추적**은 정확성 책임에서 빠졌다. "선언했지만 안 쓴 관계" 경고와 `RelationNotLoaded`의 원인 표시용으로 개발·테스트 모드에서만 켠다.
- 스냅샷은 끝까지 불변이라 스레드 간 공유가 안전하다. 쓰기는 모두 필드 연산 값으로 표현되므로 프록시가 필요 없다.

### 10.9 레지스트리와 seal

- import 중에는 가변 레지스트리에 엔티티·Repository·usecase가 등록된다.
- `seal()`은 검증을 모두 통과하면 **불변 `SealedRegistry`**를 만들고, 이후 등록 시도는 에러다. free-threaded 환경에서도 런타임에 공유되는 메타데이터에 락이 필요 없다.
- seal 검증 단계: ① 엔티티·관계·제약 해석(지연 어노테이션 평가) → ② 로드 계획 해석·컴파일 → ③ 모듈 경계 → ④ 불변식과 집합 변경 충돌 → ⑤ DTO·`@query` 매핑 → ⑥ (선택) DB 카탈로그와의 drift 비교.
- 단계가 있는 곳(ADR-0001): 순수 검사(①, ③, ④, ⑤ 중 SQL이 필요 없는 부분)는 `core/schema`에 있고, `app`이 seal을 조립하며 SQL이 필요한 단계(②는 `platina.sql`을 거쳐, ⑥은 껍데기에서)를 돌린 뒤 `SealedRegistry`를 만든다. 공개 이름은 `platina/__init__.py`가 `core`, `sql`, `app`에서만 재수출한다.

### 10.10 확장 지점: 명시적 플러그인

전역 시그널은 두지 않는다. 플러그인은 `App(plugins=[...])`로 명시적으로 등록하고, 인터페이스는 세 종류뿐이다.

| Protocol | 하는 일 | 예 |
|---|---|---|
| `ChangesTransformer` | 커밋 직전 ChangeSet을 다른 ChangeSet으로 변환 (순수) | soft delete(DELETE → `deleted_at` UPDATE), 감사 행 추가 |
| `QueryTransformer` | 로드·조회 AST에 조건 추가 (순수) | soft delete 필터, 테넌트 필터 |
| `Observer` | 실행 결과 관찰 (읽기 전용, 부수효과 허용) | 메트릭, 로그, 트레이싱 |

변환 플러그인도 순수 함수라 등록 순서대로 결정적으로 적용되고, 단위 테스트할 수 있다.

### 10.11 성능 최적화 경로

- v1은 순수 Python. 행 디코딩은 psycopg의 C 구현이 이미 맡는다.
- 핫 패스(스냅샷 생성, 플래너, 컴파일 캐시 조회)는 작은 인터페이스 뒤에 둔다. 필요하면 나중에 Rust(PyO3) 확장으로 교체한다.
- mypyc는 쓰지 않는다. mypyc는 아직 free-threaded 빌드를 지원하지 않는다. 반면 PyO3는 free-threaded Python용 확장 빌드를 지원한다.

### 10.12 예외 계층

```
PlatinaError
├── SealError                 # 기동 시 검증 실패 (모듈 경계, 불변식, 매핑)
├── UsageError                # 프로그래밍 오류, 재시도 안 함
│   ├── RelationNotLoaded
│   ├── UnloadedReference     # ref의 필드를 읽거나 ref에 .set, ==, hash()
│   ├── ChainClosed           # chain 블록 밖에서 뷰에 .set
│   ├── MovedSnapshotAccess   # chain으로 이동된 원본을 읽음 (==, hash() 포함)
│   ├── ConflictingWrites     # 한 단계 안에서 같은 필드를 두 번 씀
│   ├── IntraUsecaseConflict
│   └── CommitCycle
├── NotFound                  # 루트 ref나 필수 의존 로드의 행이 없음
├── ConcurrencyError
│   ├── RetryExhausted        # 40001/40P01 재시도 한도 초과
│   └── VersionMismatch       # expected_version 불일치 (요청 사이 낙관적 락)
└── DatabaseError             # 그 외 DB 오류, SQLSTATE와 원본 예외 보존
    └── UniqueViolation, CheckViolation, ...
(사용자 도메인 예외는 감싸지 않고 그대로 전파)
```

모든 예외는 메시지 외에 구조화된 필드(`usecase`, `entity`, `field`, `location`, `hint`)를 가진다. CLI·IDE 연동이나 테스트 단언에서 문자열 파싱이 필요 없다.

---

## 11. 테스트 전략

### 11.1 원칙

- **코어는 DB 없이 테스트한다.** 아키텍처를 sans-IO로 잡은 가장 큰 이유가 이것이다.
- **DB 의미는 진짜 PostgreSQL로 테스트한다.** 인메모리 가짜 DB는 만들지 않는다. 격리 수준, NULL 처리, 제약 같은 의미가 달라서 거짓 안심을 준다.
- **문서의 예제는 실행되는 테스트다.**

### 11.2 테스트 계층

| 계층 | 대상 | DB | 도구 | 실행 시점 |
|---|---|---|---|---|
| 코어 단위 + 속성 기반 | 필드 연산, chain 뷰·이동 표시, 플래너, 로드 단계 계획 | ✗ | pytest, Hypothesis | 모든 PR |
| 컴파일러 스냅샷 | AST → SQL 문자열 | ✗ | inline-snapshot | 모든 PR |
| 엔진 상태 기계 | 재시도, 롤백, 취소, 오류 주입 | ✗ | 준비된 응답 스크립트 | 모든 PR |
| 아키텍처 | 레이어·IO 금지 계약, sync/async 생성물 일치 | ✗ | import-linter, 생성 스크립트 `--check` | 모든 PR |
| 타입 | 공개 API의 타입 추론, 잘못된 사용이 타입 에러인지 | ✗ | pyright + mypy, `assert_type` | 모든 PR |
| 통합 | 실제 SQL 실행, 마이그레이션, outbox, 코드젠 | ✓ | docker compose, pytest-xdist | 모든 PR (최신 PG), nightly (PG 14~18) |
| 문서 | 문서의 모든 코드 블록 | ✓ | Sybil | 모든 PR |
| 동시성 | write skew, 재시도, 데드락, 스트레스 불변식 | ✓ | anyio 이벤트로 순서 제어 | nightly |
| 차등 테스트 | 컴파일러의 의미 정확성 | ✓ | Hypothesis + 참조 평가기 | nightly (2단계) |
| 호환성 스위트 | 방언별 능력 기반 공통 테스트 | ✓ | `platina.testing.suite` | 방언별 CI |
| free-threaded | 코어의 스레드 안전성 | ✗ | 3.14t + pytest-run-parallel | nightly |
| 성능 | §9 벤치마크 시나리오, 회귀 감지 | ✓ | pytest-benchmark | nightly |
| 변이 테스트 | 플래너·ChangeSet 테스트의 실효성 | ✗ | mutmut | 주 1회 |

### 11.3 코어: 속성 기반 테스트

ChangeSet과 플래너는 "법칙"으로 테스트한다. 예제 몇 개가 아니라 Hypothesis가 생성한 수천 개의 입력에서 성질이 성립하는지 본다.

```python
from hypothesis import given, strategies as st
from platina.testing.strategies import snapshots, steps, changesets, fk_schemas, load_plans
from tests.support.laws import (
    apply_sequentially, executed_stage_counts, read_through_moved_alias,
    replay_on_reference, run_chain,
)

@given(snapshots(Order), steps(Order), steps(Order))
def test_chain_equals_sequential_apply(order, f, g):
    """chain으로 f, g를 이은 결과 == f를 적용한 스냅샷 위에서 g를 실행한 결과."""
    # when
    chained = run_chain(order, f, g)                    # 헬퍼: with chain(order) ... c.changes
    # then
    assert order.applied(chained) == apply_sequentially(order, f, g)

@given(snapshots(Order), steps(Order), st.sampled_from(Order.fields()))
def test_alias_of_moved_snapshot_is_always_rejected(order, f, field):
    """chain 전에 만든 별칭으로 어떤 필드를 읽어도 예외 없이 MovedSnapshotAccess다."""
    # when
    error = read_through_moved_alias(order, f, field)   # 헬퍼: chain 전에 별칭, 블록 안에서 읽기
    # then
    assert isinstance(error, MovedSnapshotAccess)

@given(load_plans())
def test_stage_count_is_fixed_at_seal(plan):
    """로드 단계 수는 데이터와 무관하다: 어떤 조건 결과에서도 실행 단계 수 == seal에서 계산한 깊이."""
    # when
    counts = executed_stage_counts(plan)                # 헬퍼: 모든 조건 결과를 시뮬레이션
    # then
    assert counts == {plan.sealed_depth}

@given(fk_schemas().flatmap(lambda s: st.tuples(st.just(s), changesets(s))))
def test_planner_never_violates_constraints(schema_and_changes):
    """플래너가 만든 실행 순서를 참조 모델에서 재생하면 FK·유니크 제약이 한 번도 깨지지 않는다."""
    # given
    schema, changes = schema_and_changes
    # when
    violations = replay_on_reference(plan_commit(changes, schema), schema)   # 제약만 검사하는 작은 Python 모델
    # then
    assert violations == []
```

테스트는 저장소의 테스트 형식을 따른다: Given/When/Then 표시, 테스트 모듈 안 제어 흐름 금지. 조건 결과나 행 연산을 도는 반복문은 `tests/support/` 아래 헬퍼에 둔다.

### 11.4 엔진: 오류 주입을 전수로

엔진이 sans-IO라서, **모든 yield 지점에 오류를 넣어 보는 테스트**를 결정적으로 돌릴 수 있다.

```python
FAULTS = [SerializationFailure(), Deadlock(), ConnectionLost(), Cancelled()]
RETRYABLE = [SerializationFailure(), Deadlock()]
POINTS = yield_points(pay_usecase)                   # 헬퍼: 정상 흐름의 모든 yield 위치

@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("point", POINTS)
def test_fault_at_any_yield_point_never_commits_partial_state(point, fault):
    # given
    script = happy_path_script(pay_usecase)          # 정상 흐름의 (명령, 응답) 목록
    # when
    trace = replay(run_usecase(pay_usecase, ARGS, POLICY, PG), script, inject=(point, fault))
    # then
    assert trace.commits_after_error() == 0
    assert trace.ends_with_rollback_or_retry()

@pytest.mark.parametrize("fault", RETRYABLE)
@pytest.mark.parametrize("point", POINTS)
def test_retryable_fault_restarts_from_begin(point, fault):
    # when
    trace = replay(run_usecase(pay_usecase, ARGS, POLICY, PG),
                   happy_path_script(pay_usecase), inject=(point, fault))
    # then
    assert trace.restarted_from_begin()              # 재시도는 항상 로드부터
```

```python
@pytest.mark.parametrize("committed", [True, False], ids=["committed", "rolled-back"])
def test_commit_unknown_is_resolved_by_rerun_with_same_run_id(committed):
    """커밋 배치 도중 연결이 끊기면, 같은 실행 ID로 재실행해 커밋 여부를 판정한다."""
    # when
    trace = replay(run_usecase(pay_usecase, ARGS, POLICY, PG),
                   happy_path_script(pay_usecase), inject=("CommitBatch", ConnectionLost()),
                   server_state={"committed": committed})
    # then
    assert trace.second_attempt_run_id == trace.first_attempt_run_id
    assert trace.applied_once()                      # 커밋됐으면 AlreadyClaimed, 아니면 정상 실행
```

- 취소 주입 시 `CommitBatch`/`Rollback` 명령 도중에는 취소가 전달되지 않는지(shield)도 같은 방식으로 확인한다.
- `Sleep` 명령 덕분에 백오프 테스트에 실제 시간이 걸리지 않는다.

### 11.5 통합 테스트: 실제 PostgreSQL

- docker compose로 PostgreSQL을 띄우고(`make db-up`, 측정은 내구성 프로필 `make db-up-durable`), 테스트 스키마를 적용한 **템플릿 DB**를 한 번 만든다. 각 테스트는 `CREATE DATABASE … TEMPLATE`으로 복제한 DB를 받는다. 트랜잭션 롤백 방식의 격리는 쓰지 않는다. 우리 실행기가 트랜잭션 경계를 직접 소유하기 때문이다.
- pytest-xdist 워커마다 템플릿을 따로 가져서 병렬 실행한다.
- 컴파일러 스냅샷에 저장된 모든 SQL은 통합 단계에서 실제로 `PREPARE`해 문법 오류가 없는지 한 번 더 확인한다.
- 매트릭스: PR에서는 최신 PostgreSQL 하나, nightly에서는 PG 14~18 전체.

### 11.6 동시성 테스트

순서를 운에 맡기지 않고, 이벤트로 두 트랜잭션의 끼어드는 지점을 고정한다.

```python
async def test_write_skew_is_prevented(app_with_db):
    """당직 의사가 최소 1명은 남아야 한다는 규칙. 두 명이 동시에 빠지려 할 때."""
    # given
    both_loaded = Barrier(2)

    async def go_off(doctor_id):
        async with app_with_db.pause_after_load(barrier=both_loaded):   # 로드 후 대기 지점
            return await app_with_db.run(go_off_call.bind(doctor=Doctor.ref(doctor_id), shift=SHIFT))

    # when
    await gather_settled(go_off(1), go_off(2))
    # then
    on_call = await app_with_db.query(doctors.on_call(shift=SHIFT))
    assert len(on_call) >= 1                                   # 불변식 유지
    assert app_with_db.stats.retries(go_off_call) >= 1         # SSI가 한쪽을 재시도시켰음
```

```python
async def test_unrelated_commands_do_not_conflict_on_internal_tables(app_with_db):
    """서로 다른 주문을 다루는 커맨드 수백 개를 동시에 실행해도, 실행 ID·outbox INSERT 때문에
    생기는 직렬화 실패는 0이어야 한다 (내부 추가 전용 테이블 규칙 검증)."""
    # given
    calls = pay_calls_on_disjoint_orders(500)       # 헬퍼: 서로 다른 주문·지갑에 대한 pay.bind(...)
    # when
    await run_concurrently(app_with_db, calls)      # 헬퍼: app.run을 gather로 동시 실행
    # then
    assert app_with_db.stats.serialization_failures() == 0
```

- **스트레스 불변식 테스트**: 워커 N개가 임의의 계좌 이체를 수천 번 실행한 뒤, 총 잔액이 그대로인지 확인한다. 이때 재시도율도 기록해 §9의 "SERIALIZABLE 기본값의 비용" 근거로 쓴다.
- 어떤 일이 *일어나는지*를 보는 테스트는 빠른 테스트 DB를 써도 된다. *비율*(재시도율, 처리량)을 내는 것은 내구성을 켠 프로필(`make db-up-durable`)에서 돌린다. tmpfs에 fsync를 끈 DB는 커밋이 짧아 트랜잭션이 덜 겹치므로 충돌을 실제보다 적게 보여 준다.

### 11.7 차등 테스트 (2단계)

Hypothesis로 고정 스키마·데이터 위에서 임의의 조회 AST를 만들고, PostgreSQL 실행 결과와 작은 Python 참조 평가기의 결과를 비교한다. NULL과 3값 논리, 조인, 그룹핑에서 컴파일러가 의미를 바꾸는 버그를 잡는 게 목적이다. 참조 평가기 구현 비용이 커서 컴파일러가 안정된 뒤에 도입한다.

### 11.8 타입 테스트

```python
# tests/typing/pass_composition.py — pyright와 mypy 둘 다 통과해야 함
result = await app.run(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)))
assert_type(result.token, ConsistencyToken)
rows = await app.query(orders.summaries(user_id=uid))
assert_type(rows, list[OrderSummary])
assert_type(Order.status, Column[Order, OrderStatus])
assert_type(order.status, OrderStatus)
with chain(order, wallet) as (c, o2, w2):
    assert_type(o2, Order)
    assert_type(w2, Wallet)
new = Order(number="A-1", total=money, user_id=uid)              # 필수 필드 검사

# tests/typing/fail_misuse.py — 각 줄이 지정한 코드 [pyright 규칙, mypy 코드]의 타입 에러여야 함
# fmt: off
pay.bind(order=oid, wallet=w)                 # expect-error[reportArgumentType, arg-type]: UUID는 Order가 아님
pay.bind(ordr=Order.ref(oid), wallet=w)       # expect-error[reportCallIssue, call-arg]: 파라미터 이름 오타
order.set(Order.status.to(123))               # expect-error[reportArgumentType, arg-type]: int는 OrderStatus가 아님
order.status = OrderStatus.PAID               # expect-error[reportAttributeAccessIssue, misc, arg-type]: 스냅샷은 불변
order.items.append(item)                      # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: Sequence에는 append 없음
apply_coupon(o, c) + pay(o, w)                # expect-error[reportOperatorIssue, reportUnusedExpression, operator]: StepResult끼리 + 불가
orders.by_number(42)                          # expect-error[reportArgumentType, arg-type]: Finder[Order, str]
Order(number="A-1")                           # expect-error[reportCallIssue, call-arg]: 필수 필드 total, user_id 누락
# fmt: on
```

- `tools/typetests.py`가 두 체커를 돌려 표시한 줄마다 검사한다: 각 체커가 그 줄에 에러를 내야 하고, 그 줄의 에러는 모두 나열한 코드 중 하나여야 한다(`report`로 시작하면 pyright 규칙, 나머지는 mypy 코드). 코드가 없으면 엉뚱한 이유(이름 오타)로 실패하는 줄도 통과해 버린다.
- 위 코드는 스파이크 0001이 관찰한 코드다(§9.1). 일부 줄은 체커마다 코드를 둘 이상 갖는다. mypy는 불변성 줄에 `misc`(frozen)와 `arg-type`(`__set__`의 `Never` instance)을 둘 다 내고, pyright strict는 `append` 줄에 `reportUnknownMemberType`을, 맨 `+` 식에 `reportUnusedExpression`을 더한다(`_ = ...`로 쓰면 대신 `reportUnknownVariableType`이 된다).
- 마커가 줄을 길게 만든다. `ruff format`은 문장을 줄바꿈해 에러가 나는 줄에서 마커를 떼어 놓으므로, 실패 파일은 오용 블록을 `# fmt: off` / `# fmt: on`으로 감싼다.

### 11.9 호환성 스위트

SQLAlchemy의 방식처럼, 방언과 무관한 공통 테스트를 `platina.testing.suite`로 공개하고, 방언은 `DialectCapabilities`로 지원 여부를 선언한다. 지원하지 않는 기능의 테스트는 건너뛰는 게 아니라 **축소 모드 전략의 테스트로 바뀐다.** PostgreSQL 방언이 이 스위트의 첫 사용자이고, MySQL 방언은 이 스위트를 통과하는 것이 출시 조건이다.

### 11.10 free-threaded 검증

코어 단위 테스트를 3.14t에서 pytest-run-parallel로 돌린다. 이 플러그인은 테스트 스위트 전체를 병렬로 돌리는 게 아니라 같은 테스트를 여러 스레드에서 동시에 실행해 스레드 안전성 문제를 찾는다. 불변 스냅샷과 `SealedRegistry` 설계가 실제로 락 없이 안전한지를 여기서 확인한다.

### 11.11 사용자용 테스트 키트 (`platina.testing`)

| 제공 기능 | 용도 |
|---|---|
| `Entity.stub(...)` | DB 없는 유스케이스 단위 테스트용 스냅샷 |
| `Entity.ref(...)`, Finder 호출 | `bind` 인자로 넘길 자리표시자 (통합 테스트) |
| `changes.updated()`, `.inserted()`, `.events` | ChangeSet 단언 |
| `freeze_now(...)` | `Now` 주입값 고정 |
| pytest 플러그인: `pg_database`, `app_with_db` | 템플릿 DB 복제 기반 통합 테스트 픽스처 |
| `app.expect_roundtrips(max=N)` | 왕복 예산 단언 (N+1 회귀 방지) |
| `app.pause_after_load(...)` | 동시성 시나리오 재현 |
| `strategies` (Hypothesis) | 사용자 엔티티용 스냅샷·ChangeSet 생성기 |

우리가 쓰는 테스트 도구를 그대로 사용자에게도 준다. 인메모리 가짜 DB는 제공하지 않는다. 순수 유스케이스는 DB가 필요 없고, DB가 필요한 테스트는 진짜 PostgreSQL이 맞다.

---

## 출처

- Hibernate ORM 7.0 Apache 2.0 재라이선스: https://in.relation.to/2025/03/14/orm-asl/ , https://docs.hibernate.org/orm/7.0/migration-guide/
- psycopg 파이프라인 모드: https://psycopg.org/psycopg3/docs/advanced/pipeline.html
- psycopg 3.3 t-string 지원: https://www.postgresql.org/about/news/psycopg-33-released-3187/
- psycopg 비동기(asyncio·gevent): https://psycopg.org/psycopg3/docs/advanced/async.html
- psycopg Trio 지원 논의: https://github.com/psycopg/psycopg/issues/29
- PostgreSQL 직렬화 실패 처리: https://www.postgresql.org/docs/16/mvcc-serialization-failure-handling.html
- PEP 779 (free-threaded 지원 단계): https://discuss.python.org/t/pep-779-criteria-for-supported-status-for-free-threaded-python/84319/123
- PEP 649/749, annotationlib: https://docs.python.org/3/library/annotationlib.html
- PEP 810 (explicit lazy imports): https://peps.python.org/pep-0810/
- Python 3.15 출시: https://docs.python.org/3.15/whatsnew/3.15.html
- MySQL RETURNING 요청: https://bugs.mysql.com/bug.php?id=117915
- MariaDB INSERT…RETURNING: https://mariadb.com/kb/en/insertreturning/ , MariaDB 13.0 UPDATE…RETURNING: https://mariadb.com/resources/blog/announcing-mariadb-community-server-13-0-ga.md
- triopg / pgtrio: https://awesome.ecosyste.ms/projects/github.com%2Fpython-trio%2Ftriopg , https://pypi.org/project/pgtrio/0.5.1/
- Atlas 라이선스·v0.38 변경: https://atlasgo.io/features , https://dev.to/mickelsamuel/atlas-paywalled-their-migration-linter-here-are-your-free-alternatives-4god
- sqldef: https://github.com/sqldef/sqldef
- Prisma TypedSQL DB 연결 요구: https://www.prisma.io/docs/orm/v6/prisma-client/using-raw-sql/typedsql
- sqlc DB 기반 분석: https://docs.sqlc.dev/en/latest/howto/generate.html
- outbox 폴링·CDC: https://encore.dev/articles/transactional-outbox-pattern , https://oneuptime.com/blog/post/2026-07-22-transactional-outbox-duplicate-events/view
- import-linter 계약: https://import-linter.readthedocs.io/en/v2.0/contract_types.html
- PyPI 이름·휠 확인: https://pypi.org (2026-11-24 직접 조회)
- psycopg 내부 설계(제너레이터·wait, async→sync 자동 변환): https://psycopg.org/articles/tag/psycopg3 , https://www.postgresql.org/message-id/CA%2Bmi_8YaYErxx0L56Z1HdXkMmdMd-TSYZ%3DUDjQZAOSQ4zUTKPQ%40mail.gmail.com
- SQLAlchemy 컴파일 캐시: https://docs.sqlalchemy.org/en/21/faq/performance.html
- SQLAlchemy dialect compliance suite: https://sources.debian.org/src/sqlalchemy/2.0.45%2Bds1-1/README.dialects.rst
- Hibernate ActionQueue: https://vladmihalcea.com/hibernate-facts-knowing-flush-operations-order-matters/ , https://docs.hibernate.org/orm/7.2/javadocs/org/hibernate/engine/spi/ActionQueue.html , https://forum.hibernate.org/viewtopic.php?p=2431155
- Ecto Adapter behaviour: https://hexdocs.pm/ecto/3.7.0/Ecto.Adapter.Queryable.html
- free-threaded 확장 도구 지원(mypyc·PyO3): https://py-free-threading.github.io/dependencies , https://docs.rs/crate/pyo3/0.28.0/source/guide/src/free-threading.md
- pytest-run-parallel: https://pypi.org/project/pytest-run-parallel
- Python 3.14 uuid7: https://docs.python.org/3.14/library/uuid.html
- SSI의 B-tree 리프 페이지 단위 읽기 잠금: https://postgresql.org/message-id/CAHXaXTy%3DaJROA0pXXifb%3DjkvP%2B2_62s9%2BictzqkmfhOJVjHWxg%40mail.gmail.com , https://www.interdb.jp/pg/pgsql05/09.html
- 디스크립터 필드와 dataclass_transform 생성자 타입 논의(2026-10): https://discuss.python.org/t/plain-annotations-for-descriptor-backed-fields-orms-dataclass-transform/109427
- 커밋 결과 확인용 txid_status(이전 안의 근거): https://www.enterprisedb.com/blog/traceable-commit-postgresql-10
