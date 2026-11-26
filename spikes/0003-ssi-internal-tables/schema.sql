-- Spike 0003 schema. Recreated by every script before it runs (throwaway).
-- Internal tables follow design 4.6 / 8.3; business tables follow the workloads of the write-up.
-- No foreign keys: an FK check is a read and would confound attribution of 40001s.

DROP TABLE IF EXISTS run_claim, run_claim_u, run_result, outbox_log,
    orders, small_orders, wallets, accounts, products, order_items, payments, ledger, pockets,
    user_spending, store_revenue, proj_new, hot CASCADE;

-- Internal append-only tables
CREATE TABLE run_claim (id uuid PRIMARY KEY);
CREATE TABLE run_result (run_id uuid PRIMARY KEY, result jsonb NOT NULL);
CREATE TABLE outbox_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
    payload jsonb NOT NULL
);
CREATE INDEX outbox_log_xid ON outbox_log (xid);
-- Control "INSERT then UPDATE": a claim table that gets updated with the result
CREATE TABLE run_claim_u (id uuid PRIMARY KEY, result jsonb);

-- Business tables
CREATE TABLE orders (
    id uuid PRIMARY KEY,
    user_id bigint NOT NULL,
    store_id int NOT NULL,
    status text NOT NULL,
    total numeric NOT NULL,
    version int NOT NULL
);
CREATE INDEX orders_user ON orders (user_id, id);
CREATE TABLE small_orders (LIKE orders INCLUDING ALL);
CREATE TABLE wallets (id bigint PRIMARY KEY, balance numeric NOT NULL, version int NOT NULL);
CREATE TABLE accounts (id bigint PRIMARY KEY, balance numeric NOT NULL, version int NOT NULL);
CREATE TABLE products (id int PRIMARY KEY, price numeric NOT NULL);
CREATE TABLE order_items (
    id uuid PRIMARY KEY, order_id uuid NOT NULL, product_id int NOT NULL,
    qty int NOT NULL, price numeric NOT NULL
);
CREATE TABLE payments (id uuid PRIMARY KEY, order_id uuid NOT NULL, amount numeric NOT NULL);
CREATE TABLE ledger (
    id uuid PRIMARY KEY, from_id bigint NOT NULL, to_id bigint NOT NULL, amount numeric NOT NULL
);
-- Write-skew workload of section D: a user may spend from either pocket while the sum of both
-- stays >= 0 (a rule over the read set that no single row carries).
CREATE TABLE pockets (
    user_id bigint, kind int, balance numeric NOT NULL, PRIMARY KEY (user_id, kind)
);

-- Projection targets
CREATE TABLE user_spending (user_id bigint PRIMARY KEY, total numeric NOT NULL);
CREATE TABLE store_revenue (store_id int PRIMARY KEY, total numeric NOT NULL);
CREATE TABLE proj_new (id uuid PRIMARY KEY, total numeric NOT NULL);

-- C4: one hot row that every command increments (ADR-0005)
CREATE TABLE hot (id int PRIMARY KEY, bal numeric NOT NULL);

-- Fill factor of the business and projection tables. Sections A-C use 70 so that updates of
-- non-indexed columns stay HOT (no index insertion that would conflict with readers of the same
-- leaf page and confound attribution); section D resets it to the default 100 (realistic) and
-- records the HOT ratio. Callers run set_fillfactor() in common.py.
