# GRA Income Tax Calculator (Python / Flask + PostgreSQL, for Vercel)

Pages: choose the tax year, choose annual or monthly, calculator tabs (Calculate Tax, Quarterly Tax,
Remaining Tax, Find Chargeable Income, Bulk Calculation) and a password-protected Rate Settings area.

## Files

    app.py                 the Flask app (all pages and downloads)
    schema.sql             the database tables (created automatically on first start)
    init_db.py             optional: create the tables from the command line
    gra/db.py              database connection (PostgreSQL, or SQLite when no DATABASE_URL is set)
    gra/rates.py           tax bands <-> database
    gra/security.py        password, lockout, temporary results, CSRF
    gra/bulk.py, calc.py   bulk file processing and the tax calculations
    templates/, static/, public/static/    pages, CSS/JS/logo (static files are included twice so Vercel serves them either way)

## The database

    tax_years (year PK)
        |  1 --- many  (ON DELETE CASCADE)
        +-- tax_bands (year, period, position, width, rate)       the annual / monthly bands of each year
        |  1 --- many  (ON DELETE CASCADE)
        +-- bulk_results (token PK, tax_year, period, mode, data, created_at, expires_at)
                                                                     TEMPORARY results, deleted after expires_at
    settings_auth (id = 1, password_hash, failed_attempts, locked_until)   the Rate Settings password

* Deleting a tax year removes its bands and any temporary results of that year.
* **No uploaded document is ever stored.** Files are read in memory and dropped. Only the calculated results are kept so the
  Download buttons work, and each row is deleted after `RETENTION_MINUTES` (default 30). Expired rows are deleted on every
  page visit, and "delete them now" removes them immediately.
* `settings_auth.password_hash = NULL` means the default password is still in use.

## Connecting a database (recommended: Neon Postgres through Vercel)

Neon is free to start, is built into Vercel, and fills in the connection settings for you.

1. Push this folder to GitHub and **Import** it in Vercel (Add New > Project). Vercel detects the Flask app (`app.py`).
2. In the Vercel project open **Storage** > **Create Database** > choose **Neon (Postgres)** > pick a region near your users
   (e.g. a European one for Ghana) > **Create**.
3. When asked, **Connect** the database to this project (all environments). Vercel adds `DATABASE_URL` (and `POSTGRES_URL`) to
   the project automatically. You do not need to copy anything.
4. Open **Settings > Environment Variables** and add:

   | Name | Value | |
   |------|-------|---|
   | `SECRET_KEY` | a long random text: `python -c "import secrets;print(secrets.token_hex(32))"` | required |
   | `SETTINGS_DEFAULT_PASSWORD` | first Rate Settings password (default `GRA@Rates2026`) | optional |
   | `RETENTION_MINUTES` | minutes before results are deleted (default `30`) | optional |
   | `SETTINGS_IDLE_MINUTES` | Rate Settings idle sign-out (default `15`) | optional |

5. **Redeploy** (Deployments > ... > Redeploy). On the first visit the app creates the tables and fills in the 2026 and 2027
   tax bands. Open the site, go to Rate Settings, log in and change the default password.
6. To check: Neon console > **Tables** (or Vercel Storage > your database > Open in Neon) should show `tax_years`, `tax_bands`,
   `settings_auth` and `bulk_results`. Optionally paste `schema.sql` into Neon's **SQL Editor** to create them by hand.

### Other options

* **Supabase**: create a project, then *Project Settings > Database > Connection string > Transaction pooler* and add it in
  Vercel as `DATABASE_URL`. Or use the Supabase integration in the Vercel Marketplace (it sets `POSTGRES_URL`).
* **Any Postgres** (Railway, Render, Aiven, your own server): set `DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require`.
* From your computer, `DATABASE_URL="..." python init_db.py` creates the tables without opening the site.
* On Vercel use the provider's **pooled** connection string (Neon's host contains `-pooler`) because every request opens a new connection.

If `DATABASE_URL` is not set the app uses a temporary SQLite file. That is fine on your own computer, but on Vercel the data would
be lost, and Rate Settings shows a warning.

## Security

* **Rate Settings password**: viewing, adding, editing and deleting bands needs it. Stored hashed in `settings_auth`.
  Forgot it? Run `UPDATE settings_auth SET password_hash = NULL;` in the Neon SQL Editor to return to the default password.
  Auto sign-out after 15 minutes idle; 5 wrong tries lock the login for 5 minutes.
* CSRF protection on the Rate Settings forms; HTTP-only, SameSite cookies (secure on Vercel).

## Limits on Vercel

A request (one bulk upload) is limited to about 4.5 MB: the app allows 4 MB per file / 4.4 MB per upload (up to 50,000 rows per file).

## Run on your own computer

    python -m venv .venv
    .venv\Scripts\activate          (Windows)   |   source .venv/bin/activate   (Mac/Linux)
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000 (uses SQLite unless `DATABASE_URL` is set).
