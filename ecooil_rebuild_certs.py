# -*- coding: utf-8 -*-
"""
Rebuild lost אישורי פריקה from the ריכוז data through Limor's own Word
templates (Gadot 2025 folder was accidentally deleted from Z:).

Fills the merge fields of a template docx with a row's values by direct
XML surgery (no Word mail-merge run, no data-source prompt), strips the
mail-merge connection from the copy, and leaves a ready docx. PDF export
is done afterwards in one Word COM batch (see the PowerShell step).

PILOT MODE: --pilot builds ONE sanitary 1719 certificate for Limor's review.
Output goes to C:\eco_oil_portal\שחזור גדות 2025\ — NOT to Z:.
"""
import os, re, sys, shutil, zipfile
sys.stdout.reconfigure(encoding="utf-8")
os.environ.pop("DATABASE_URL", None)

from src.app import create_app
from src.app.db import EcoOilUnloadEvent

TEMPLATES = {
    "סניטרי שלוח אקו": r"Z:\Eco_General\דגם אישורים\סניטרי_שלוח אקו_מקושר.docx",
    "סניטרי":          r"Z:\Eco_General\דגם אישורים\סניטרי_מקושר.docx",
    "בסיס":            r"Z:\Eco_General\דגם אישורים\בסיס_מקושר.docx",
    "מי שטיפה":        r"Z:\Eco_General\דגם אישורים\מי שטיפה_מקושר.docx",
    "מינרלי":          r"Z:\Eco_General\דגם אישורים\מינרלי_קוביה_מקושר.docx",
    "אמולסיה":         r"Z:\Eco_General\דגם אישורים\אמולסיה_מקושר.docx",
    "חומצה":           r"Z:\Eco_General\דגם אישורים\חומצה_מקושר.docx",
    "צמחי":            r"Z:\Eco_General\דגם אישורים\צמחי_מקושר.docx",
}
OUT_DIR = r"C:\eco_oil_portal\שחזור גדות 2025"

FLD_BEGIN = '<w:fldChar w:fldCharType="begin"/>'
FLD_END = '<w:fldChar w:fldCharType="end"/>'

def esc_xml(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def fill_fields(xml, values):
    """Replace every MERGEFIELD block with a literal run of the mapped value,
    keeping the placeholder run's formatting."""
    out, pos = [], 0
    while True:
        b = xml.find(FLD_BEGIN, pos)
        if b < 0:
            out.append(xml[pos:])
            break
        run_start = max(xml.rfind("<w:r ", pos, b), xml.rfind("<w:r>", pos, b))
        e = xml.find(FLD_END, b)
        if e < 0:
            out.append(xml[pos:])
            break
        end_run_close = xml.find("</w:r>", e) + len("</w:r>")
        block = xml[run_start:end_run_close]
        m = re.search(r"MERGEFIELD.*?instrText[^>]*>\s*([^< ]+)", block, re.S)
        if not m:
            m2 = re.search(r'MERGEFIELD\s+"?([^"\\ <]+)', re.sub(r"</?w:[^>]+>", "", block))
            field = m2.group(1) if m2 else None
        else:
            field = m.group(1).strip()
        # formatting: take rPr of the placeholder («...») run if present
        pm = re.search(r"<w:r(?:>|\s[^>]*>)((?:(?!</w:r>).)*?«[^»]*»(?:(?!</w:r>).)*?)</w:r>", block, re.S)
        rpr = ""
        if pm:
            rm = re.search(r"<w:rPr>.*?</w:rPr>", pm.group(1), re.S)
            if rm:
                rpr = rm.group(0)
        val = values.get(field, "")
        val = "" if val is None else str(val)
        repl = f"<w:r>{rpr}<w:t xml:space=\"preserve\">{esc_xml(val)}</w:t></w:r>" if val else ""
        out.append(xml[pos:run_start])
        out.append(repl)
        pos = end_run_close
    return "".join(out)

def strip_mailmerge(settings_xml):
    return re.sub(r"<w:mailMerge>.*?</w:mailMerge>", "", settings_xml, flags=re.S)

def build_docx(template, values, out_path):
    with zipfile.ZipFile(template) as z:
        names = z.namelist()
        doc = z.read("word/document.xml").decode("utf-8")
        settings = z.read("word/settings.xml").decode("utf-8") if "word/settings.xml" in names else None
    doc = fill_fields(doc, values)
    if "«" in re.sub(r"<[^>]+>", "", doc):
        raise RuntimeError(f"placeholder left unfilled in {out_path}")
    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = doc.encode("utf-8")
            elif item.filename == "word/settings.xml" and settings is not None:
                data = strip_mailmerge(settings).encode("utf-8")
            zout.writestr(item, data)

def row_values(ev):
    return {
        "תאריך": ev.event_date.strftime("%d/%m/%Y") if ev.event_date else "",
        "לקוח": ev.customer or "",
        "כתובת": ev.address or "",
        "חיוב": ev.billed_to or "",
        "משקל_מוצהר": f"{ev.declared_tons:.2f}" if ev.declared_tons is not None else "",
        "סוג_אריזה": ev.package_type or "",
        "מס_אריזות": ev.package_count if ev.package_count is not None else "",
        "הערות": ev.notes or "",
        "חברת_ההובלה": ev.transporter or "",
        "שעת_יציאה": ev.exit_time or "",
        "קוד_רנדומלי": ev.code or "",
    }

def out_name(ev, stream_word):
    d = ev.event_date
    client_short = "מיכל 1719 צ- 19" if "1719" in (ev.customer or "") else (ev.customer or "")
    client_short = re.sub(r'[\\/:*?"<>|]', "_", client_short)[:80]
    return f"{stream_word}_{d.day}.{d.month}.{str(d.year)[2:]}_{client_short}.docx"

def pick_template(stream):
    """Template + filename stream-word for a ריכוז stream value."""
    s = stream or ""
    if "סניטרי" in s:
        return TEMPLATES["סניטרי שלוח אקו"], "סניטרי"   # Gadot sanitary = the שלוח אקו deal
    for key in ("מי שטיפה", "מינרלי", "אמולסיה", "בסיס", "חומצה", "צמחי"):
        if key in s:
            return TEMPLATES[key], key
    return None, None

def clean_name(s):
    s = re.sub(r'[\\/:*?"<>|]', "_", s or "").strip()
    return re.sub(r"\s+", " ", s)[:80]

app = create_app()
with app.app_context():
    os.makedirs(OUT_DIR, exist_ok=True)
    pilot = "--pilot" in sys.argv
    q = (EcoOilUnloadEvent.query
         .filter(EcoOilUnloadEvent.pdf_path.is_(None),
                 EcoOilUnloadEvent.year == 2025,
                 EcoOilUnloadEvent.billed_to.contains("גדות אחסון"))
         .order_by(EcoOilUnloadEvent.event_date))
    rows = q.all()
    if pilot:
        ev = next(r for r in rows if r.stream and "סניטרי" in r.stream and r.exit_time)
        tpl = TEMPLATES["סניטרי שלוח אקו"]
        name = out_name(ev, "סניטרי_שלוח אקו")
        out = os.path.join(OUT_DIR, name)
        build_docx(tpl, row_values(ev), out)
        print("PILOT ROW:", ev.event_date, "|", ev.customer, "|", ev.stream,
              "|", ev.declared_tons, "טון |", ev.exit_time, "| קוד:", ev.code or "(אין)")
        print("WROTE:", out)
    else:
        built, skipped = [], []
        for ev in rows:
            tpl, word = pick_template(ev.stream)
            if not tpl or not ev.event_date:
                skipped.append(ev)
                continue
            d = ev.event_date
            if "1719" in (ev.customer or ""):
                cname = "מיכל 1719 צ- 19"
            else:
                cname = clean_name(ev.customer)
            month_dir = os.path.join(OUT_DIR, str(d.month))
            os.makedirs(month_dir, exist_ok=True)
            base = f"{word}_{d.day}.{d.month}.25_{cname}"
            out = os.path.join(month_dir, base + ".docx")
            n = 2
            while os.path.exists(out):                 # same-day repeats → _2 suffix
                out = os.path.join(month_dir, f"{base}_{n}.docx")
                n += 1
            vals = row_values(ev)
            vals["הערות"] = ""    # internal remarks must not reach a customer document
            build_docx(tpl, vals, out)
            built.append((ev, out))
        print(f"נבנו {len(built)} קבצי וורד | דולגו {len(skipped)}:")
        for ev in skipped:
            print("   דולג:", ev.event_date, "|", ev.stream, "|", ev.customer,
                  f"(גיליון {ev.source_sheet} שורה {ev.source_row})")
