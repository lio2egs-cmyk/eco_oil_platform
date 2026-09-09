# -*- coding: utf-8 -*-
"""שער הקבצים — הגשת מסמכים מהאחסון (B2) דרך הכתובת של הפורטל.

למה (ענבל/ישקר, 09/09/2026): עד היום כל "צפייה"/"הורדה" החזירה ללקוח קישור
חתום ישירות לשרת האחסון (s3.eu-central-003.backblazeb2.com). מערכת הסינון
של ישקר חוסמת את כל קטגוריית "אחסון ענן" — הלקוחה ראתה את הפורטל תקין
ונחסמה רק ברגע פתיחת הקובץ. מעכשיו הדפדפן של הלקוח פונה רק לכתובת
הפורטל (portal./depot.eco-oil.co.il), והשרת מושך את הקובץ מהאחסון ומזרים
אותו הלאה. האחסון נשאר פרטי, וכתובתו לא מופיעה יותר אצל אף לקוח.

המנגנון: signed_file_url() מחזיר קישור יחסי /files/<token> — הטוקן חתום
(itsdangerous, מפתח ה-JWT), תקף 5 דקות, נושא את מפתח הקובץ, שם הקובץ
ואופן ההגשה (צפייה/הורדה). ההרשאה נבדקת בנקודת הקצה שמייצרת את הקישור
(אותם שערים בדיוק כמו קודם); הקישור עצמו הוא "מפתח חד-מטרתי" קצר-חיים,
בדיוק כמו ה-presigned URL שהחליף — רק על הדומיין שלנו.
"""
import os
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, stream_with_context
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

file_gate = Blueprint("file_gate", __name__)

LINK_SECONDS = 300          # כמו PRESIGN_SECONDS שהיה — 5 דקות
_SALT = "eco-file-gate-v1"
_CHUNK = 64 * 1024
B2_VARS = ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET_CERTS", "B2_ENDPOINT")


def storage_configured():
    return all(os.environ.get(v) for v in B2_VARS)


def _serializer():
    return URLSafeTimedSerializer(current_app.config["JWT_SECRET_KEY"], salt=_SALT)


def signed_file_url(key, filename, disposition="attachment", content_type=None):
    """קישור קצר-חיים על הדומיין שלנו למפתח אחסון שכבר אושר להגשה.
    disposition: 'inline' (צפייה) או 'attachment' (הורדה)."""
    payload = {"k": key, "n": filename, "d": disposition}
    if content_type:
        payload["t"] = content_type
    return "/files/" + _serializer().dumps(payload)


def _s3():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=f"https://{os.environ['B2_ENDPOINT']}",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        config=Config(signature_version="s3v4"),
    )


@file_gate.route("/files/<path:token>", methods=["GET"])
def serve_file(token):
    try:
        p = _serializer().loads(token, max_age=LINK_SECONDS)
    except SignatureExpired:
        return jsonify(error="expired",
                       message="הקישור פג תוקף — חזרו לפורטל ולחצו שוב"), 410
    except BadSignature:
        return jsonify(error="bad link"), 404
    if not storage_configured():
        return jsonify(error="storage not configured"), 503
    try:
        obj = _s3().get_object(Bucket=os.environ["B2_BUCKET_CERTS"], Key=p["k"])
    except Exception:
        current_app.logger.warning("file gate: missing B2 key %s", p["k"])
        return jsonify(error="no file", message="הקובץ אינו זמין באחסון"), 404

    body = obj["Body"]

    def gen():
        try:
            while True:
                chunk = body.read(_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    disp = "inline" if p.get("d") == "inline" else "attachment"
    headers = {
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(p['n'])}",
        "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff",
    }
    if obj.get("ContentLength") is not None:
        headers["Content-Length"] = str(obj["ContentLength"])
    ctype = p.get("t") or obj.get("ContentType") or "application/octet-stream"
    return Response(stream_with_context(gen()), mimetype=ctype, headers=headers)
