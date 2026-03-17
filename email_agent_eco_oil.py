"""
Email Agent - Eco Oil
=====================
שולח אוטומטית מיילים עם אישורי פריקה כל יום חמישי בצהריים.
לצורך הדגמה: השליחה מודפסת לטרמינל במקום לשלוח בפועל.
במערכת האמיתית: יש להגדיר SMTP_USER ו-SMTP_PASSWORD ב-.env
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import schedule
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SMTP_USER = os.getenv("SMTP_USER", "demo@eco-oil.co.il")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "demo_password")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

def get_unsent_certificates():
    """שולף מהמסד את כל אישורי הפריקה שטרם נשלחו"""
    from app import create_app
    from app.db import DisposalCertificate, DisposalEvent

    app = create_app()
    with app.app_context():
        certs = DisposalCertificate.query.filter(
            DisposalCertificate.sent_at == None
        ).all()

        results = []
        for cert in certs:
            event = cert.disposal_event
            results.append({
                "cert_id": cert.id,
                "certificate_number": event.certificate_number,
                "client_name": event.client_name or "לא ידוע",
                "billed_to": event.billed_to,
                "sent_to_email": cert.sent_to_email or event.client_name,
                "event_date": event.event_date.strftime("%d/%m/%Y"),
                "material_classification": event.material_classification,
                "weight_net": event.weight_net,
            })
        return results

def mark_as_sent(cert_id, email):
    """מסמן אישור כנשלח במסד"""
    from app import create_app
    from app.db import db, DisposalCertificate

    app = create_app()
    with app.app_context():
        cert = DisposalCertificate.query.get(cert_id)
        if cert:
            cert.sent_at = datetime.utcnow()
            cert.sent_to_email = email
            db.session.commit()

def send_certificate_email(cert_data):
    """שולח מייל עם אישור פריקה ללקוח"""

    subject = f"אישור פריקה מס' {cert_data['certificate_number']} - אקו אויל חץ וירומטל בע\"מ"

    body = f"""שלום,

מצורף אישור פריקה מס' {cert_data['certificate_number']}.

פרטי האירוע:
- לקוח: {cert_data['client_name']}
- תאריך: {cert_data['event_date']}
- סיווג חומר: {cert_data['material_classification']}
- משקל נטו: {cert_data['weight_net']} ק"ג

לפרטים נוספים ניתן לפנות למשרד אקו אויל.

בברכה,
אקו אויל חץ וירומטל בע"מ
טל: 04-8494996
office@eco-oil.co.il
"""

    recipient = cert_data.get("sent_to_email") or "unknown@client.com"

    if DEMO_MODE:
        print("=" * 60)
        print(f"[DEMO] שליחת מייל — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        print(f"  אל: {recipient}")
        print(f"  נושא: {subject}")
        print(f"  גוף:\n{body}")
        print("=" * 60)
        return True, recipient
    else:
        # חיבור אמיתי ל-Microsoft 365 SMTP
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            msg = MIMEMultipart()
            msg["From"] = SMTP_USER
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP("smtp.office365.com", 587) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

            return True, recipient
        except Exception as e:
            print(f"[שגיאה] שליחת מייל נכשלה: {e}")
            return False, recipient

def weekly_send_job():
    """המשימה השבועית — רצה כל יום חמישי בצהריים"""
    print(f"\n[Agent] מתחיל שליחה שבועית — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    certs = get_unsent_certificates()

    if not certs:
        print("[Agent] אין אישורים חדשים לשליחה השבוע.")
        return

    print(f"[Agent] נמצאו {len(certs)} אישורים לשליחה.")

    sent_count = 0
    for cert in certs:
        success, recipient = send_certificate_email(cert)
        if success:
            mark_as_sent(cert["cert_id"], recipient)
            sent_count += 1

    print(f"[Agent] סיים — נשלחו {sent_count}/{len(certs)} אישורים.")

def run_now():
    """הרצה מיידית לצורך בדיקה והדגמה"""
    print("[Agent] הרצה ידנית לצורך הדגמה...")
    weekly_send_job()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        # הרצה מיידית לבדיקה
        run_now()
    else:
        # תזמון אוטומטי — כל יום חמישי בשעה 12:00
        print("[Agent] Email Agent אקו אויל מופעל.")
        print("[Agent] ימתין ויריץ כל יום חמישי בשעה 12:00.")
        print("[Agent] להרצה מיידית: python email_agent_eco_oil.py --now")

        schedule.every().thursday.at("12:00").do(weekly_send_job)

        while True:
            schedule.run_pending()
            time.sleep(60)