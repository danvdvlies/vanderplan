# Vanderplan — Zero-Based Budgeting

A personal zero-based / envelope budgeting web app (YNAB-style), built with
Django + server-rendered templates and an AdminKit-inspired Bootstrap 5 UI.

> Given the money I have right now, what jobs have I assigned it to, what bills
> are due, what future expenses am I underfunded for, and how much do I need to
> assign this month?

## Stack

- Python 3.12+ / Django 5.x, Django ORM + migrations only
- SQLite locally, PostgreSQL-ready via `DATABASE_URL` (nothing DB-specific outside `DATABASES`)
- `DecimalField` for **all** money — never floats
- Django auth from day one; every model is user-owned and every query is user-scoped
- Bootstrap 5 + Bootstrap Icons (CDN), WhiteNoise for static files in production

## Quick start

```bash
python3.12 -m venv .venv          # any Python >= 3.10
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env              # defaults to SQLite, DEBUG=True
python manage.py migrate
python manage.py seed_data --user demo --password budget123   # optional sample data
python manage.py createsuperuser  # optional, for /admin
python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in (`demo` / `budget123` if you seeded).

## Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True` locally, `False` in production |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | `sqlite:///db.sqlite3` or `postgres://user:pass@host:5432/db` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated origins for production HTTPS |
| `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | HTTPS hardening toggles |

### Switching to PostgreSQL

Only the environment changes — no model or code changes:

```bash
DATABASE_URL=postgres://user:password@host:5432/dbname
python manage.py migrate
```

## How the budgeting math works

Calculations live in [`budget/services.py`](budget/services.py), kept free of
SQLite-specific SQL so the same code runs on Postgres.

- **Available balance** rolls forward month to month. The recursive spec
  formula `available(m) = available(m-1) + assigned(m) + activity(m)` telescopes
  to *all assignments + all activity up to and including the month*, computed
  with two aggregate queries.
- **To be assigned** = total cash available − total available across categories.
  Credit-card balances are excluded from cash (documented MVP assumption).
- **Needed this month**:
  - Due this month / overdue / undated → the full remaining shortfall.
  - Due in the future → shortfall spread across the remaining months, rounded
    **up** to the cent so funding it each month actually reaches the target.

  Example: $220 due in 3 months with $0 saved → **$73.34/month** (220 ÷ 3,
  rounded up). A note on the spec: its prose defines `months_remaining` as
  "inclusive", but its own worked example and success criterion #11 require
  220 ÷ 3 = 73.34. The code follows the worked example; see the docstring on
  `months_remaining`.
- **Funded %** = `min(100, available / target × 100)`; zero target → 0.
- **Repeating goals** advance the due date by `repeat_interval_months` via the
  "Advance" button on the Goals screen.

## Screens

Dashboard · Budget month · Accounts · Categories · Transactions · Goals — plus
Django admin at `/admin/`.

## Tests

```bash
python manage.py test
```

Covers the required cases (spec §13): available roll-forward, expense/assignment
effects, goal-due-this-month vs future vs overdue, funded %, repeating-goal
advance, and that one user cannot see or reach another user's data.

## Deployment notes

- Set `DEBUG=False`, a real `SECRET_KEY`, `ALLOWED_HOSTS`, and `DATABASE_URL`.
- `python manage.py collectstatic` (WhiteNoise serves hashed/compressed assets).
- Run under `gunicorn config.wsgi` behind a reverse proxy that terminates HTTPS.
- HSTS, secure cookies, and SSL redirect activate automatically when `DEBUG=False`.

## Not in the MVP

Bank syncing, credit-card special handling, recurring-transaction automation,
sharing between users, forecasting, investments, multi-currency, receipts, AI
categorisation.
