# -*- coding: utf-8 -*-
"""זהות קבועה לשורת פריקה של אקו-אויל (לימור 17/09/2026).

למה: עד היום כל סבב שעתי מחק את כל שורות האויל בענן והכניס אותן מחדש, וכל
שורה קיבלה מספר זיהוי חדש. לקוחה שפתחה את רשימת המסמכים לפני הסבב ולחצה
על מסמך אחריו קיבלה "הקובץ אינו זמין כרגע" (רחל / אור ברקן, 16/09 14:02).
מעכשיו לכל שורה יש מפתח טבעי שנגזר מהשדות שמזהים אותה בריכוז, הענן מעדכן
שורות במקום, והמשרד שולח רק את מה שהשתנה מאז הסבב הקודם (כמו גיבוי).

המפתח נגזר מ: שנה, חודש, גיליון מקור, מס' תעודה, קוד רנדומלי, תאריך,
לקוח, זרם. שינוי באחד מהם = שורה חדשה (מספר זיהוי חדש) — נדיר ומקובל.
שינוי בכל שדה אחר (הערות, משקלים, קובץ, סטטוס פרסום) = עדכון במקום.
שתי שורות זהות בכל השדות האלה (לא קרה בתמונת 17/09) מקבלות סיומת #2, #3
לפי סדר השורה בגיליון — כך המפתח תמיד ייחודי בתוך תמונה אחת.

הפונקציה משותפת למשרד (ecooil_bridge_push.py) ולענן (ecooil_bridge.py) —
הגדרה אחת, כדי ששני הצדדים יסכימו תמיד על הזהות של כל שורה.
"""
import hashlib

IDENTITY_FIELDS = ("year", "month", "source_sheet", "serial", "code",
                   "event_date", "customer", "stream")


def _norm(v):
    if v is None:
        return ""
    s = str(v).strip()
    # תאריך מגיע כ-date בצד הענן וכמחרוזת ISO מהמשרד — אותו ייצוג
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else s


def identity_string(item):
    """המחרוזת הגולמית שמזהה שורה (לפני גיבוב) — לצורכי אבחון."""
    return "|".join(_norm(item.get(f)) for f in IDENTITY_FIELDS)


def nat_key(item):
    """מפתח טבעי בסיסי (בלי סיומת כפילות): 40 תווים hex."""
    return hashlib.sha1(identity_string(item).encode("utf-8")).hexdigest()


def assign_nat_keys(items):
    """מציבה item['nat_key'] לכל פריט ברשימה; כפילויות מקבלות סיומת #n לפי
    סדר source_row (ואז לפי סדר הרשימה). מחזירה את מספר הכפילויות שנמצאו."""
    order = sorted(range(len(items)),
                   key=lambda i: ((items[i].get("source_row") or 0), i))
    seen = {}
    dups = 0
    for i in order:
        base = nat_key(items[i])
        n = seen.get(base, 0) + 1
        seen[base] = n
        if n == 1:
            items[i]["nat_key"] = base
        else:
            items[i]["nat_key"] = f"{base}#{n}"
            dups += 1
    return dups
