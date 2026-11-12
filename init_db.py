"""Optional: create the tables (and put in the built-in 2026/2027 tax bands) without starting the website.

    DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require" python init_db.py
"""
from app import app
from gra.db import get_db
from gra.rates import load_rates

with app.app_context():
    get_db()                 # creates the tables from schema.sql
    years = load_rates()     # fills in the built-in tax years the first time
    print("Database ready. Tax years:", ", ".join(str(y) for y in years))
