<!-- i18n: source=README.md source-sha256=05a270e177d0 translation-sha256=aea7efdf6f6f -->
# Platina

원문(영어): [README.md](README.md)

> *Platina*는 백금(platinum)의 옛 스페인어 이름이다. 백금이 산에도 녹지 않고 반응하지 않듯,
> 도메인 코드는 DB와 반응하지 않는다.

Platina는 Python 3.14+와 PostgreSQL용 ORM이고, 규칙 하나 위에 서 있다. **도메인 코드는 DB가
존재한다는 사실을 몰라야 한다.** 유스케이스는 필요한 데이터를 시그니처에 선언하고, 불변
스냅샷을 받는 순수 함수로 실행되며, 변경을 데이터로 돌려준다. 모든 IO는 한 곳
(`app.run` / `app.query`)에서, 라이브러리가 소유한 트랜잭션 안에서 일어나고, 기본값은
SERIALIZABLE과 자동 재시도다.

```python
type PayableOrder = Annotated[Order, orders.payable]

@usecase
def pay(order: PayableOrder, wallet: Annotated[Wallet, Load()], now: Now = INJECTED) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    return (
        order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))
        + wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))
    )

await app.run(pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(user_id)))
```

## 상태

**설계 확정, 구현은 막 시작함.** 지금은 예외 계층(`platina.PlatinaError`와 하위 클래스)만 있고, 위 코드는 목표 문법이며 동작하는 API가 아니다. 스파이크 세
개가 끝났다: 타입 표면([`docs/spikes/0001-type-surface.md`](docs/spikes/0001-type-surface.md)),
종이 위에 옮긴 실제 유스케이스 10개([`docs/spikes/0002-use-cases-on-paper.md`](docs/spikes/0002-use-cases-on-paper.md)),
SSI 동시성([`docs/spikes/0003-ssi-internal-tables.md`](docs/spikes/0003-ssi-internal-tables.md)).
설계 문서의 나머지 실험(Alembic 왕복, 측정)이 프로토타입의 나머지보다 먼저다.

- 설계 문서: [`docs/design/design.md`](docs/design/design.md) (한국어: [`design-KO.md`](docs/design/design-KO.md))
- 현재 아키텍처: [`docs/architecture.md`](docs/architecture.md)
- 설계 문서 이후의 결정: [`docs/adr/`](docs/adr/)
- 저장소 개발 방식(코딩 에이전트 + 사람 메인테이너):
  [`docs/workflow.md`](docs/workflow.md) (한국어: [`workflow-KO.md`](docs/workflow-KO.md))

## 개발

[uv](https://docs.astral.sh/uv/)가 필요하고, 통합 테스트에는 Docker가 필요하다.

```bash
uv sync              # 의존성
make check           # 빠른 게이트: lint, pyright + mypy, 가드, 단위·타입 테스트
make db-up           # PostgreSQL 18, localhost:26432
make check-all       # 통합 테스트까지 전부
make help            # 전체 타깃
```

에이전트와 사람은 같은 규칙을 따른다: [`AGENTS.md`](AGENTS.md).

## 라이선스

Apache-2.0.
