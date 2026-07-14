# -*- coding: utf-8 -*-
"""Generate a static HTML preview of the isotank view from the synced data,
so Limor can open it in her browser and see real tanks in the real layout."""
import os, html
from datetime import date
from collections import Counter

os.environ.pop("DATABASE_URL", None)
from src.app import create_app
from src.app.db import DepotIsotankVisit

OUT = r"C:\eco_oil_portal\תצוגה מקדימה - מבט איזוטנקים.html"
GREETING = ("ברוכים הבאים לפורטל הלקוחות של אקו-דיפו. "
            "כל המידע על המכלים, השטיפות והמסמכים שלכם מרוכז, מעודכן וזמין לכם כאן.")

def status_color(s):
    s = s or ""
    if "ממתין" in s: return "#FFF2CC"
    if "תיקון" in s: return "#F8CBAD"
    if "שחרור" in s or "מוכן" in s: return "#C6E0B4"
    if "נשטף" in s or "שטיפ" in s: return "#FCE4D6"
    if "אחסנ" in s or "אחסון" in s: return "#DDEBF7"
    return "#ECECEC"

app = create_app()
with app.app_context():
    in_storage = DepotIsotankVisit.query.filter(DepotIsotankVisit.exit_site_date.is_(None)).all()
    counts = Counter(v.company for v in in_storage if v.company)
    cand = [(c, n) for c, n in counts.items() if 4 <= n <= 30]
    company = (min(cand, key=lambda x: abs(x[1] - 12))[0] if cand
               else (counts.most_common(1)[0][0] if counts else None))
    rows = [v for v in in_storage if v.company == company] if company else []
    rows.sort(key=lambda v: (v.storage_in_date or v.arrival_date or date.min), reverse=True)
    rows = rows[:30]
    today = date.today()

    def days(v):
        d = v.storage_in_date or v.arrival_date
        return (today - d).days if d else None
    def fmt(d):
        return d.strftime("%d/%m/%Y") if d else "—"
    def esc(x):
        return html.escape(str(x)) if x not in (None, "") else "—"

    trs = []
    for v in rows:
        sc = status_color(v.status)
        d = days(v)
        trs.append(f"""<tr>
          <td class="num">{esc(v.isotank_number)}</td>
          <td class="store">{fmt(v.storage_in_date or v.arrival_date)}</td>
          <td class="store days">{d if d is not None else '—'}</td>
          <td><span class="chip" style="background:{sc}">{esc(v.status)}</span></td>
          <td>{esc(v.last_material)}</td>
          <td>{esc(v.un_number)}</td>
          <td>{esc(v.hazard_class)}</td>
        </tr>""")

    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>פורטל הדיפו — מבט איזוטנקים</title>
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f6;margin:0;color:#2b2b2b}}
  .wrap{{max-width:1000px;margin:0 auto;padding:18px}}
  .top{{background:#5B9E96;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0}}
  .top h1{{margin:0;font-size:21px}}
  .greet{{background:#EAF3F1;padding:12px 22px;font-size:14px;line-height:1.6;border-right:4px solid #5B9E96}}
  .bar{{display:flex;gap:10px;align-items:center;background:#fff;padding:12px 22px;border-bottom:1px solid #e7e7e7;flex-wrap:wrap}}
  .tab{{padding:7px 16px;border-radius:20px;font-weight:700;font-size:14px}}
  .tab.on{{background:#5B9E96;color:#fff}} .tab.off{{background:#eef2f1;color:#5B9E96}}
  .search{{margin-inline-start:auto;background:#f1f5f4;color:#888;padding:8px 14px;border-radius:8px;font-size:13px}}
  .meta{{padding:10px 22px;background:#fff;font-size:13px;color:#666}}
  table{{width:100%;border-collapse:collapse;background:#fff}}
  th,td{{padding:10px 8px;text-align:center;font-size:13.5px;border-bottom:1px solid #eee}}
  thead.grp th{{background:#3E6F69;color:#fff;font-size:12px;padding:6px}}
  thead.col th{{background:#f0f4f3;color:#3E6F69;font-weight:700}}
  td.num{{font-weight:700}} td.store{{background:#F6FAFC}} td.days{{font-weight:800;background:#FDF3E3}}
  .chip{{display:inline-block;padding:4px 12px;border-radius:14px;font-weight:700;font-size:12.5px}}
  .foot{{padding:14px 22px;font-size:12.5px;color:#888;background:#fff;border-radius:0 0 12px 12px}}
</style></head><body><div class="wrap">
  <div class="top"><h1>פורטל הדיפו &middot; מבט איזוטנקים — המכלים שלי במגרש האחסנה</h1></div>
  <div class="greet">שלום, {esc(company)} 👋<br>{GREETING}</div>
  <div class="bar">
    <span class="tab on">איזוטנקים</span><span class="tab off">רואדטנקים</span>
    <span class="search">🔍 חיפוש מכל לפי מספר…</span>
  </div>
  <div class="meta">מוצגים {len(rows)} מכלים שנמצאים כעת במגרש האחסנה &middot; נתונים אמיתיים שסונכרנו מהקובץ</div>
  <table>
    <thead class="grp"><tr><th>מספר מכל</th><th colspan="2">אחסנה</th><th>שלב טיפול</th><th colspan="3">פרטי המטען</th></tr></thead>
    <thead class="col"><tr><th></th><th>תאריך כניסה לאחסנה</th><th>ימי אחסנה</th><th></th><th>חומר אחרון</th><th>מספר אום</th><th>קבוצת סיכון</th></tr></thead>
    <tbody>{''.join(trs)}</tbody>
  </table>
  <div class="foot">זוהי תצוגה מקדימה להמחשת חיבור הנתונים. העיצוב הסופי, התפור לקו של אתר אקו-אויל, ייעשה בשלב הבא.</div>
</div></body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(page)
print(f"WROTE {OUT}\ncompany={company} rows={len(rows)} total_in_storage={len(in_storage)}")
