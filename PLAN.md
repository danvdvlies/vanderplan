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

All planned features shipped.
