"""
Email Agent - Eco Depot
=======================
קורא מיילים נכנסים של בקשות PreArrival מ-Outlook,
מחלץ מהם נתונים באמצעות AI ויוצר PreArrival אוטומטית במערכת.
לצורך הדגמה: קריאת המייל מגיעה מטקסט לדוגמה במקום מ-Outlook אמיתי.
במערכת האמיתית: יש להגדיר OUTLOOK_USER ו-OUTLOOK_PASSWORD ב-.env
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

OUTLOOK_USER = os.getenv("OUTLOOK_USER", "depot@eco-oil.co.il")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_PASSWORD", "demo_password")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
FLASK_BASE_URL = os.getenv("FLASK_BASE_URL", "http://127.0.0.1:5000")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# מייל לדוגמה לצורך הדגמה
DEMO_EMAIL = """
מאת: logistics@company-example.co.il
נושא: בקשה לשירות שטיפה — טנק מספר ABC-1234

שלום,

אנו מבקשים לתאם שירות שטיפה לרואדטנקר מספר ABC-1234.
החומר האחרון שהובל: חומצה גופרתית.
מספר תאים: 3
שירות מבוקש: שטיפה + בדיקת לחץ

יש לנו היתר MSDS מצורף.

בתודה,
דוד כהן
לוגיסטיקה בע"מ
"""


def read_emails_from_outlook():
    """
    קורא מיילים נכנסים מ-Outlook באמצעות Microsoft Graph API.
    לצורך הדגמה — מחזיר מייל לדוגמה.
    במערכת האמיתית: יש לחבר Microsoft Graph API עם OAuth2.
    """
    if DEMO_MODE:
        print("[Agent דיפו] מצב דמו — משתמש במייל לדוגמה.")
        return [{"id": "demo_001", "body": DEMO_EMAIL, "subject": "בקשה לשירות שטיפה — טנק מספר ABC-1234"}]
    else:
        # חיבור אמיתי ל-Microsoft Graph API
        # נדרש: רישום אפליקציה ב-Azure Active Directory
        # TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        # GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages"
        print("[Agent דיפו] חיבור ל-Outlook אמיתי — טרם הוגדר.")
        return []


def extract_pre_arrival_data(email_body):
    """
    מחלץ נתוני PreArrival ממייל חופשי באמצעות Claude API.
    מחזיר dict עם הנתונים שחולצו.
    """
    if DEMO_MODE or not ANTHROPIC_API_KEY:
        print("[Agent דיפו] מצב דמו — משתמש בנתוני דמו לחילוץ.")
        return {
            "asset_identifier": "ABC-1234",
            "asset_type": "roadtanker",
            "client_name": "לוגיסטיקה בע\"מ",
            "msds_chemical_name": "חומצה גופרתית",
            "requested_service": "שטיפה + בדיקת לחץ",
            "declared_compartments_count": 3,
            "notes": "חולץ אוטומטית ממייל",
            "has_msds": True,
        }

    prompt = f"""אתה מחלץ נתונים ממייל בקשת שירות לחברת שטיפת מכלים.
    
חלץ מהמייל הבא את הנתונים הבאים בפורמט JSON בלבד (ללא טקסט נוסף):
{{
  "asset_identifier": "מספר הטנק/נכס",
  "asset_type": "roadtanker או isotank",
  "client_name": "שם החברה השולחת",
  "msds_chemical_name": "שם החומר האחרון",
  "requested_service": "השירות המבוקש",
  "declared_compartments_count": מספר_תאים_או_null,
  "has_msds": true_או_false,
  "notes": "הערות נוספות"
}}

המייל:
{email_body}

החזר JSON בלבד."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[Agent דיפו] שגיאה בחילוץ AI: {e}")
        return None


def find_or_create_client(client_name):
    """מחפש לקוח קיים או יוצר חדש"""
    try:
        res = requests.get(f"{FLASK_BASE_URL}/clients")
        if res.status_code == 200:
            clients = res.json().get("clients", [])
            for c in clients:
                if c["name"] == client_name:
                    return c["id"]
    except Exception:
        pass

    # יצירת לקוח חדש
    try:
        res = requests.post(f"{FLASK_BASE_URL}/clients", json={
            "name": client_name,
            "division": "eco_depot",
            "client_type": "direct"
        })
        if res.status_code == 201:
            return res.json().get("client_id")
    except Exception as e:
        print(f"[Agent דיפו] שגיאה ביצירת לקוח: {e}")
    return None


def find_or_create_asset(identifier, asset_type):
    """מחפש נכס קיים או יוצר חדש"""
    try:
        res = requests.get(f"{FLASK_BASE_URL}/assets")
        if res.status_code == 200:
            assets = res.json().get("assets", [])
            for a in assets:
                if a["identifier"] == identifier:
                    return a["id"]
    except Exception:
        pass

    # יצירת נכס חדש
    try:
        res = requests.post(f"{FLASK_BASE_URL}/assets", json={
            "identifier": identifier,
            "division": "eco_depot",
            "asset_type": asset_type or "roadtanker"
        })
        if res.status_code == 201:
            return res.json().get("asset_id")
    except Exception as e:
        print(f"[Agent דיפו] שגיאה ביצירת נכס: {e}")
    return None


def create_pre_arrival(data, asset_id, client_id):
    """יוצר PreArrival במערכת"""
    try:
        payload = {
            "asset_id": asset_id,
            "client_id": client_id,
            "msds_chemical_name": data.get("msds_chemical_name"),
            "requested_service": data.get("requested_service"),
            "declared_compartments_count": data.get("declared_compartments_count"),
            "notes": data.get("notes", ""),
        }
        res = requests.post(f"{FLASK_BASE_URL}/depot/pre-arrivals", json=payload)
        if res.status_code == 201:
            return res.json()
    except Exception as e:
        print(f"[Agent דיפו] שגיאה ביצירת PreArrival: {e}")
    return None


def process_email(email):
    """מעבד מייל אחד — מחלץ נתונים ויוצר PreArrival"""
    print(f"\n[Agent דיפו] מעבד מייל: {email['subject']}")

    # שלב 1 — חילוץ נתונים
    data = extract_pre_arrival_data(email["body"])
    if not data:
        print("[Agent דיפו] לא ניתן לחלץ נתונים מהמייל.")
        return False

    print(f"[Agent דיפו] נתונים שחולצו: {json.dumps(data, ensure_ascii=False, indent=2)}")

    # שלב 2 — מציאת/יצירת לקוח
    client_id = find_or_create_client(data.get("client_name", "לקוח לא ידוע"))
    if not client_id:
        print("[Agent דיפו] לא ניתן למצוא/ליצור לקוח.")
        return False

    # שלב 3 — מציאת/יצירת נכס
    asset_id = find_or_create_asset(
        data.get("asset_identifier", "UNKNOWN"),
        data.get("asset_type", "roadtanker")
    )
    if not asset_id:
        print("[Agent דיפו] לא ניתן למצוא/ליצור נכס.")
        return False

    # שלב 4 — יצירת PreArrival
    if DEMO_MODE:
        print(f"[Agent דיפו] [DEMO] יוצר PreArrival עבור נכס {asset_id} ולקוח {client_id}")
        print(f"[Agent דיפו] [DEMO] PreArrival נוצר בהצלחה!")
        return True
    else:
        result = create_pre_arrival(data, asset_id, client_id)
        if result:
            print(f"[Agent דיפו] PreArrival נוצר בהצלחה: {result}")
            return True
        return False


def run_agent():
    """הרצה ראשית של ה-Agent"""
    print(f"\n[Agent דיפו] מתחיל עיבוד מיילים — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    emails = read_emails_from_outlook()

    if not emails:
        print("[Agent דיפו] אין מיילים חדשים לעיבוד.")
        return

    print(f"[Agent דיפו] נמצאו {len(emails)} מיילים לעיבוד.")

    success_count = 0
    for email in emails:
        if process_email(email):
            success_count += 1

    print(f"\n[Agent דיפו] סיים — עובדו {success_count}/{len(emails)} מיילים בהצלחה.")


if __name__ == "__main__":
    run_agent()