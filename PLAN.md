# Roadmap

Tracked plan for the next batch of features. Built in the order below, each as
its own commit with tests. Checked items are shipped.

## Shared refactor (prerequisite)

- [ ] Extract a reusable `_transaction_row.html` (and `_transaction_table.html`)
      partial from `transaction_list.html`, so the category drill-down, the
      per-account register, and the transactions list all render rows the same
      way (and an inline "cleared" toggle lives in one place).

## 1. Category-detail drill-down

Focused page per category (envelope).

- [ ] `category_detail/<pk>/` view (ownership-checked).
- [ ] Header: name, group, current Available, active goal + funded % bar
      (reuse `build_category_row`).
- [ ] Monthly history table: last N months of Assigned / Activity / Available
      via a new `category_history(user, category, num_months)` service.
- [ ] This category's transactions (shared row partial), filterable by month.
- [ ] Quick actions: assign (to Budget), edit category, "Add transaction"
      prefilled with this category.
- [ ] Links in from `budget_month.html` and `category_list.html`.
- [ ] Tests: history values per month, ownership 404, scoped transactions.

No model changes.

## 2. CSV export / import

### Export (small)
- [ ] "Export CSV" on the transactions list, respecting active filters.
- [ ] Streamed response; columns: date, account, payee, category, amount, memo,
      cleared, is_income.

### Import (medium)
- [ ] Canonical Vanderplan CSV (same columns as export) so export/import
      round-trips; downloadable template.
- [ ] Flow: upload -> preview/validate -> commit.
- [ ] Per-row: parse date & Decimal amount; match category by name (unmatched ->
      Uncategorised, never auto-create); choose target account.
- [ ] Duplicate detection on (account, date, amount, payee); user can skip.
- [ ] Safety: file-size / row-count caps; atomic bulk insert; per-row errors.

No model changes. A bank-specific column-mapping UI is a later enhancement.

## 3. Reconciliation / clearing balance

`Transaction.cleared` already exists; this turns it into a workflow.

- [ ] Add `reconciled` (bool) + `reconciled_at` (nullable) to Transaction
      (migration).
- [ ] `account_balances(account)` -> cleared / uncleared / working.
- [ ] Per-account register page with inline cleared toggle and the three
      balances.
- [ ] `reconcile_account(account, statement_balance, date)`: create a
      cleared+reconciled adjustment for any difference; mark cleared rows
      reconciled.
- [ ] Reconciled rows render locked (edit/delete disabled with a warning).
- [ ] Tests: balance breakdown, reconcile with/without difference, adjustment
      creation, lock behaviour.

Optional later: a `Reconciliation` history model.
