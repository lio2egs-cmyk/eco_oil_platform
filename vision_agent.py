"""
Vision Agent - זיהוי מספר לוחית רישוי / מספר מכל
===================================================
מקבל תמונה, שולח ל-Claude Vision API לזיהוי,
ומחזיר קישור לנכס המתאים במסד.
לצורך הדגמה: אפשר להשתמש בתמונת דמו.
במערכת האמיתית: מסופון מצלם ושולח תמונה ישירות.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import base64
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FLASK_BASE_URL = os.getenv("FLASK_BASE_URL", "http://127.0.0.1:5000")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"


def encode_image(image_path):
    """ממיר תמונה ל-base64"""
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def identify_number_from_image(image_path):
    """
    שולח תמונה ל-Claude Vision ומקבל מספר לוחית/מכל.
    מחזיר dict עם הנתונים שזוהו.
    """
    if DEMO_MODE or not ANTHROPIC_API_KEY:
        print("[Vision] מצב דמו — מחזיר מספר לדוגמה.")
        return {
            "identified_number": "ABC-1234",
            "number_type": "tank",  # tank / vehicle
            "confidence": "high",
            "raw_text": "ABC-1234",
        }

    try:
        import anthropic
        image_data = encode_image(image_path)

        # זיהוי סוג הקובץ
        ext = image_path.lower().split(".")[-1]
        media_type_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
        media_type = media_type_map.get(ext, "image/jpeg")

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        }
                    },
                    {
                        "type": "text",
                        "text": """זהה את המספר המופיע בתמונה זו.
זה יכול להיות:
1. לוחית רישוי של רכב (מספר רכב)
2. מספר מזוהה על גוף מכל/טנק

החזר JSON בלבד בפורמט הבא:
{
  "identified_number": "המספר שזוהה",
  "number_type": "vehicle או tank",
  "confidence": "high / medium / low",
  "raw_text": "הטקסט המלא שנראה בתמונה"
}

אם לא זוהה מספר, החזר identified_number כ-null."""
                    }
                ]
            }]
        )

        raw = message.content[0].text.strip()
        return json.loads(raw)

    except Exception as e:
        print(f"[Vision] שגיאה בזיהוי: {e}")
        return None


def find_asset_by_identifier(identifier):
    """מחפש נכס במסד לפי מספר מזהה"""
    try:
        res = requests.get(f"{FLASK_BASE_URL}/assets")
        if res.status_code == 200:
            assets = res.json().get("assets", [])
            for asset in assets:
                if asset["identifier"].upper() == identifier.upper():
                    return asset
    except Exception as e:
        print(f"[Vision] שגיאה בחיפוש נכס: {e}")
    return None


def get_asset_action_url(asset):
    """מחזיר קישור לשורת הפעולה של הנכס"""
    asset_id = asset["id"]
    asset_type = asset["asset_type"]
    division = asset["division"]

    return {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "division": division,
        "status_url": f"{FLASK_BASE_URL}/assets/{asset_id}/status",
        "action_url": f"{FLASK_BASE_URL}/depot/assets/{asset_id}/wash-cycles" if asset_type == "roadtanker" else f"{FLASK_BASE_URL}/depot/assets/{asset_id}/isotank-wash-cycles",
        "photo_upload_url": f"{FLASK_BASE_URL}/depot/assets/{asset_id}/photos",
    }


def process_image(image_path=None):
    """
    הפונקציה הראשית — מעבדת תמונה ומחזירה קישור לנכס.
    אם לא סופקה תמונה — משתמשת בדמו.
    """
    print(f"\n[Vision] מתחיל עיבוד תמונה...")

    # שלב 1 — זיהוי מספר
    if image_path and os.path.exists(image_path):
        print(f"[Vision] מעבד תמונה: {image_path}")
        result = identify_number_from_image(image_path)
    else:
        print("[Vision] לא סופקה תמונה — משתמש בדמו.")
        result = identify_number_from_image(None)

    if not result or not result.get("identified_number"):
        print("[Vision] לא זוהה מספר בתמונה.")
        return None

    identified = result["identified_number"]
    number_type = result["number_type"]
    confidence = result["confidence"]

    print(f"[Vision] זוהה: {identified} (סוג: {number_type}, ביטחון: {confidence})")

    # שלב 2 — חיפוש נכס במסד
    asset = find_asset_by_identifier(identified)

    if not asset:
        print(f"[Vision] נכס עם מספר '{identified}' לא נמצא במסד.")
        return {
            "identified_number": identified,
            "number_type": number_type,
            "asset_found": False,
            "message": f"נכס '{identified}' לא קיים במערכת — יש ליצור אותו.",
            "create_url": f"{FLASK_BASE_URL}/assets",
        }

    # שלב 3 — קישור לשורת פעולה
    action_links = get_asset_action_url(asset)

    print(f"[Vision] נכס נמצא: {asset['identifier']} (סוג: {asset['asset_type']})")
    print(f"[Vision] קישור לפעולה: {action_links['action_url']}")
    print(f"[Vision] קישור להעלאת תמונות: {action_links['photo_upload_url']}")

    return {
        "identified_number": identified,
        "number_type": number_type,
        "confidence": confidence,
        "asset_found": True,
        "asset": asset,
        "links": action_links,
    }


if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    result = process_image(image_path)

    if result:
        print(f"\n[Vision] תוצאה סופית:")
        print(json.dumps(result, ensure_ascii=False, indent=2))