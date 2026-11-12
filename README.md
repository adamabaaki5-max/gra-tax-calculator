# GRA Income Tax Calculator (Python / Flask, for Vercel)

The same program as the PHP version, rewritten in Python (Flask). Pages: choose the tax year, choose annual or
monthly, calculator tabs (Calculate Tax, Quarterly Tax, Remaining Tax, Find Chargeable Income, Bulk Calculation),
and a password-protected Rate Settings area. Photo reading is not included.

## Files

    app.py               the Flask app (all pages and downloads)
    gra/                 calculations, bulk processing, rates, security, storage
    templates/           HTML pages
    static/, public/static/   CSS, JS and logo (same files twice, so they are served either way on Vercel)
    requirements.txt     Flask and openpyxl

## Deploy on Vercel

1. Put this folder in a Git repository (GitHub/GitLab/Bitbucket) and import it in Vercel, or run `vercel` from this folder.
   Vercel detects the Flask app (`app.py`) automatically.
2. **Connect a database (needed).** Vercel's file system is read-only and does not keep files, so saved tax bands, the
   Rate Settings password and the temporary bulk results are kept in Redis.
   In the Vercel dashboard: *Storage* > *Create* / *Marketplace* > **Upstash Redis** (free plan is enough) > connect it to
   this project. Vercel adds `KV_REST_API_URL` and `KV_REST_API_TOKEN` itself. Nothing else to configure.
3. In *Settings > Environment Variables* add:

   | Name | Value | Required |
   |------|-------|----------|
   | `SECRET_KEY` | a long random text (e.g. run `python -c "import secrets;print(secrets.token_hex(32))"`) | yes |
   | `SETTINGS_DEFAULT_PASSWORD` | the first Rate Settings password (default `GRA@Rates2026`) | optional |
   | `RETENTION_MINUTES` | minutes before uploaded data/results are deleted (default `30`) | optional |
   | `SETTINGS_IDLE_MINUTES` | Rate Settings sign-out after inactivity (default `15`) | optional |

4. Redeploy after adding variables.

Without the database the app still runs, but anything saved is kept only in the temporary folder of one server
instance and will disappear; Rate Settings shows a warning when this is the case.

## Security

* **Automatic deletion.** Uploaded files are read in memory and never written to disk. The calculation results kept for the
  download buttons are stored in Redis with an expiry (30 minutes by default), so the database removes them by itself.
  After that the download links stop working. A "delete them now" link is shown with the results.
* **Rate Settings password.** Viewing, adding, editing and deleting tax bands needs the password. Default `GRA@Rates2026`
  (or `SETTINGS_DEFAULT_PASSWORD`). Change it in Rate Settings > Change password; the new password is stored hashed in Redis and
  the default stops working. If it is forgotten, delete the key `gra:auth` in the Upstash console to go back to the default.
  Sign-out after 15 minutes of inactivity; 5 wrong tries lock the login for 5 minutes.
* Forms in Rate Settings are protected against cross-site requests (CSRF); cookies are HTTP-only and secure on Vercel.

## Limits on Vercel

* A request (so one bulk upload) can be at most about **4.5 MB** in total. The app allows 4 MB per file and 4.4 MB per upload;
  split larger files. Up to 50,000 rows per file.
* Results are compressed before being stored; extremely large result sets may not fit in the free Redis request size
  and will show a message asking you to upload fewer rows.

## Run on your own computer

    python -m venv .venv
    .venv\Scripts\activate          (Windows)   |   source .venv/bin/activate   (Mac/Linux)
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000. Without Redis, data is kept in a temporary folder (set `GRA_DATA_DIR` to choose another).
