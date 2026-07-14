# -*- coding: utf-8 -*-
"""Static HTML previews of the Eco-Oil portal 'My Documents' screen,
built from the real synced ריכוז data — one for a direct customer,
one for a transporter (per the Area-3 decisions, 2026-07-12)."""
import os, html
from collections import Counter

os.environ.pop("DATABASE_URL", None)
from src.app import create_app
from src.app.db import EcoOilUnloadEvent

OUT_DIR = r"C:\eco_oil_portal"
GREETING = ("ברוכים הבאים לפורטל הלקוחות של אקו-אויל. "
            "אישורי הפריקה, טופסי המלווה וההצהרות שלכם — מרוכזים, מעודכנים וזמינים כאן.")

def esc(x):
    return html.escape(str(x)) if x not in (None, "") else "—"

def fmt_date(d):
    return d.strftime("%d/%m/%Y") if d else "—"

def fmt_tons(v):
    return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"

STYLE = """
  body{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f6;margin:0;color:#2b2b2b}
  .wrap{max-width:1060px;margin:0 auto;padding:18px}
  .top{background:#5B9E96;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0}
  .top h1{margin:0;font-size:21px}
  .greet{background:#EAF3F1;padding:12px 22px;font-size:14px;line-height:1.6;border-right:4px solid #5B9E96}
  .bar{display:flex;gap:10px;align-items:center;background:#fff;padding:12px 22px;border-bottom:1px solid #e7e7e7;flex-wrap:wrap}
  .tab{padding:7px 16px;border-radius:20px;font-weight:700;font-size:13.5px}
  .tab.on{background:#5B9E96;color:#fff} .tab.off{background:#eef2f1;color:#5B9E96}
  .search{margin-inline-start:auto;background:#f1f5f4;color:#888;padding:8px 14px;border-radius:8px;font-size:13px}
  .meta{padding:10px 22px;background:#fff;font-size:13px;color:#666}
  table{width:100%;border-collapse:collapse;background:#fff}
  th,td{padding:9px 8px;text-align:center;font-size:13.5px;border-bottom:1px solid #eee}
  thead th{background:#3E6F69;color:#fff;font-weight:700;font-size:13px}
  td.date{font-weight:700;background:#F6FAFC}
  td.qty{font-weight:800}
  .chip{display:inline-block;padding:3px 12px;border-radius:14px;font-weight:700;font-size:12.5px;background:#DDEBF7}
  .dl{display:inline-block;padding:4px 10px;border-radius:8px;background:#5B9E96;color:#fff;font-size:12px;font-weight:700;margin:1px}
  .dl.alt{background:#8FBCB6}
  .code{font-family:Consolas,monospace;font-size:12px;color:#666}
  .foot{padding:14px 22px;font-size:12.5px;color:#888;background:#fff;border-radius:0 0 12px 12px}
"""

def stream_chip(s):
    return f'<span class="chip">{esc(s)}</span>'

def render(out_name, title, account, meta_line, filters_html, head_cells, row_cells, rows):
    trs = "".join("<tr>" + row_cells(r) + "</tr>" for r in rows)
    page = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>{esc(title)}</title>
<style>{STYLE}</style></head><body><div class="wrap">
  <div class="top"><h1>פורטל אקו-אויל &middot; המסמכים שלי</h1></div>
  <div class="greet">שלום, {esc(account)} 👋<br>{GREETING}</div>
  <div class="bar">{filters_html}<span class="search">🔍 חיפוש לפי תאריך / לקוח…</span></div>
  <div class="meta">{meta_line}</div>
  <table>
    <thead><tr>{head_cells}</tr></thead>
    <tbody>{trs}</tbody>
  </table>
  <div class="foot">זוהי תצוגה מקדימה להמחשת חיבור הנתונים האמיתיים מקובץ הריכוז.
  כפתורי ההורדה יחוברו לקבצים בשלב הבא; העיצוב הסופי ייתפר לקו של אתר אקו-אויל.</div>
</div></body></html>"""
    path = os.path.join(OUT_DIR, out_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path

app = create_app()
with app.app_context():
    # ---------- direct customer view: ישקר ----------
    direct = (EcoOilUnloadEvent.query
              .filter(EcoOilUnloadEvent.customer.contains("ישקר"))
              .order_by(EcoOilUnloadEvent.event_date.desc())
              .all())
    d_rows = direct[:25]
    years = sorted({e.event_date.year for e in direct if e.event_date}, reverse=True)
    year_tabs = "".join(
        f'<span class="tab {"on" if i == 0 else "off"}">{y}</span>'
        for i, y in enumerate(years))
    streams = [s for s, _ in Counter(e.stream for e in direct if e.stream).most_common()]
    stream_tabs = "".join(f'<span class="tab off">{esc(s)}</span>' for s in streams[:4])

    def d_cells(e):
        cert_btn = ('<span class="dl">⬇ אישור פריקה</span>' if e.pdf_path
                    else '<span class="dl" style="background:#ccc">אין קובץ</span>')
        return (f'<td class="date">{fmt_date(e.event_date)}</td>'
                f'<td>{stream_chip(e.stream)}</td>'
                f'<td class="qty">{fmt_tons(e.declared_tons)}</td>'
                f'<td>{esc(e.transporter)}</td>'
                f'<td class="code">{esc(e.code)}</td>'
                f'<td>{cert_btn}'
                f'<span class="dl alt">⬇ טופס מלווה</span></td>')

    p1 = render(
        "תצוגה מקדימה - המסמכים שלי - לקוח ישיר.html",
        "פורטל אקו-אויל — המסמכים שלי (לקוח ישיר)",
        d_rows[0].customer if d_rows else "לקוח",
        f"נמצאו {len(direct)} אישורי פריקה &middot; מוצגים 25 האחרונים &middot; ממוינים מהחדש לישן",
        f'{year_tabs}<span class="tab off">|</span>{stream_tabs}',
        ("<th>תאריך</th><th>זרם</th><th>כמות (טון)</th><th>מוביל</th>"
         "<th>קוד אישור</th><th>מסמכים להורדה</th>"),
        d_cells, d_rows)

    # ---------- transporter view ----------
    # SCOPING RULE (Limor 2026-07-13): a transporter sees ONLY unloads where THEY
    # are the billed party (their own private customers). Unloads they drove for
    # Eco-Oil's DIRECT customers (billed = the customer) belong to that customer's
    # account — mirrors the filing convention (PDF goes to the billed party's folder).
    trans_name = 'ע.ח. שאיבות בע"מ'
    trans = (EcoOilUnloadEvent.query
             .filter(EcoOilUnloadEvent.transporter == trans_name,
                     EcoOilUnloadEvent.billed_to == trans_name)
             .order_by(EcoOilUnloadEvent.event_date.desc())
             .all())
    t_rows = trans[:25]
    t_years = sorted({e.event_date.year for e in trans if e.event_date}, reverse=True)
    t_year_tabs = "".join(
        f'<span class="tab {"on" if i == 0 else "off"}">{y}</span>'
        for i, y in enumerate(t_years))
    n_customers = len({e.customer for e in trans if e.customer})

    def t_cells(e):
        cert_btn = ('<span class="dl">⬇ אישור פריקה</span>' if e.pdf_path
                    else '<span class="dl" style="background:#ccc">אין קובץ</span>')
        return (f'<td class="date">{fmt_date(e.event_date)}</td>'
                f'<td style="text-align:right;font-weight:700">{esc(e.customer)}</td>'
                f'<td>{stream_chip(e.stream)}</td>'
                f'<td class="qty">{fmt_tons(e.declared_tons)}</td>'
                f'<td class="code">{esc(e.code)}</td>'
                f'<td>{cert_btn}</td>')

    p2 = render(
        "תצוגה מקדימה - המסמכים שלי - מוביל.html",
        "פורטל אקו-אויל — המסמכים שלי (מוביל)",
        trans_name,
        (f"נמצאו {len(trans)} אישורי פריקה עבור {n_customers} לקוחות קצה "
         f"&middot; מוצגים 25 האחרונים"),
        (f'{t_year_tabs}<span class="tab off">|</span>'
         f'<span class="tab on">רשימה לפי תאריך</span>'
         f'<span class="tab off">קיבוץ לפי לקוח</span>'),
        ("<th>תאריך</th><th>לקוח (המקור)</th><th>זרם</th><th>כמות (טון)</th>"
         "<th>קוד אישור</th><th>מסמכים</th>"),
        t_cells, t_rows)

print(f"direct: {len(direct)} rows -> {p1}")
print(f"transporter '{trans_name}': {len(trans)} rows -> {p2}")
