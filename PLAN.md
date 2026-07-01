# Roadmap

Tracked plan for the next batch of features. Built in the order below, each as
its own commit with tests. Checked items are shipped.

## Shared refactor (prerequisite)

- [x] Extract a reusable `_transaction_row.html` (and `_transaction_table.html`)
      partial from `transaction_list.html`, so the category drill-down, the
      per-account register, and the transactions list all render rows the same
      way (and an inline "cleared" toggle lives in one place).

## 1. Category-detail drill-down — DONE

- [x] `category_detail/<pk>/` view (ownership-checked).
- [x] Header: name, group, current Available, active goal + funded % bar.
- [x] Monthly history table via `category_history()`.
- [x] This category's transactions (shared partial), filterable by month.
- [x] Quick actions: Budget, edit, "Add transaction" prefilled.
- [x] Links in from `budget_month.html`, `category_list.html`, transaction rows.
- [x] Tests.

## 2. CSV export / import — DONE

### Export
- [x] "Export CSV" on the transactions list, respecting active filters.
- [x] Streamed response; canonical columns; header-only blank template.

### Import
- [x] Canonical Vanderplan CSV (round-trips with export).
- [x] Flow: upload -> preview/validate -> commit (csv held in a hidden field).
- [x] Per-row: parse date & Decimal amount; match category by name (unmatched ->
      Uncategorised); choose target account.
- [x] Duplicate detection on (account, date, amount, payee); user can skip.
- [x] Safety: 2 MB / 5000-row caps; atomic insert; per-row error reporting.

## 3. Reconciliation / clearing balance — DONE

- [x] Add `reconciled` (bool) + `reconciled_at` (nullable) to Transaction
      (migration 0003).
- [x] `account_balances(account)` -> cleared / uncleared / working.
- [x] Per-account register page with inline cleared toggle and the three
      balances.
- [x] `reconcile_account(account, statement_balance, date)`: create a
      cleared+reconciled adjustment for any difference; mark cleared rows
      reconciled.
- [x] Reconciled rows render locked; edit/delete/toggle blocked server-side.
- [x] Tests.

Optional later: a `Reconciliation` history model.

---

## 4. Scenario planner (what-if affordability) — DONE

Model a big "what if" (new place, car, school fees) on top of the real budget
without touching it.

- [x] `Scenario` + `ScenarioLine` models (migration 0004); no existing model
      changed.
- [x] `scenario_summary()` reads real last-3-month income/spending averages
      (income overridable) and adds scenario monthly expenses/income + one-off
      upfront costs. `replaces_current` expense lines count only the delta over
      the linked category's current average spend.
- [x] Planner page: affordable/short verdict, today-vs-scenario table, upfront
      cash + months-to-save, line editor. Scenarios CRUD + sidebar "Planning".
- [x] Read-only over the real budget — never writes accounts/transactions/
      assignments. Tests cover the math + ownership.

## 5. Multiple budgets / the girls' own budget — IN PROGRESS

Decisions: (1) scope by `budget`; keep `user` on rows as the creator/audit
reference (no delete). (2) Support both a shared family budget *and* each girl
her own budget with goals — both fall out of membership. (3) Invite by existing
username. (4) Defer duplicate-budget and per-budget currency.

### Phase A — Budget container (multiple budgets, single user)  — DONE
- [x] `Budget(owner, name, is_default)` model.
- [x] `budget` FK on every domain model; `user` retained as nullable
      creator/audit. Budget-based unique constraints.
- [x] Migrations 0005-0008: schema, data backfill (one default Budget per user),
      make budget required, make user nullable.
- [x] Active budget via session + `ActiveBudgetMiddleware` (`request.budget`);
      top-bar switcher; budgets manage page (create / rename / set default /
      delete, with last-budget guard).
- [x] Services/views/forms scoped by budget; new budgets seed starter categories.
- [x] All tests updated to a budget context + new test_budgets (isolation,
      switching, guards). 107 tests green on SQLite and PostgreSQL.

### Phase B — Sharing, roles & auth hardening
- [ ] `BudgetMembership(budget, user, role)` — owner / editor / viewer.
- [ ] Access by membership; viewer = read-only; owner manages members.
- [ ] Invite by existing username; Members page.
- [ ] **Folded-in auth/security** (these arrive with real multi-user):
      - [ ] Self-service password reset + change-password views.
      - [ ] Email backend (SMTP/provider) for reset links.
      - [ ] `django-axes` login rate-limiting / lockout (brute-force protection).
      - [ ] Production checklist: registration closed by default, real
            SECRET_KEY, HTTPS enforced (already wired), optional 2FA.

---

Scenario planner shipped; Phase A of multiple-budgets is in progress.
