import sqlite3

# 1) מציג טבלאות שקיימות בפועל בקובץ DB
conn = sqlite3.connect("data/app.db")
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()
print("Tables:", [t[0] for t in tables])

# 2) מציג את כל מחזורי השטיפה לפי compartment (כי זה המודל החדש)
from src.app import create_app
from src.app.db import WashCycle

app = create_app()
with app.app_context():
    print("Wash cycles (all, by compartment):")
    cycles = (
        WashCycle.query
        .order_by(WashCycle.compartment_id, WashCycle.cycle_number)
        .all()
    )
    for c in cycles:
        print(
            f"compartment_id={c.compartment_id}, "
            f"cycle_number={c.cycle_number}, "
            f"chemical_used={c.chemical_used}, "
            f"result={c.result}, "
            f"checked_by_role={c.checked_by_role}, "
            f"checked_by_name={c.checked_by_name}"
        )