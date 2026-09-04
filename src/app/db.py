from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import deferred
from datetime import datetime

db = SQLAlchemy()


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    division = db.Column(db.String(50), nullable=False)  # eco_oil / eco_depot
    client_type = db.Column(db.String(50))  # direct / indirect / agent
    parent_client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    # Additional billed-party spellings this client owns (newline-separated):
    # former names, absorbed companies, per-site billed names, ריכוז spelling variants.
    billing_aliases = db.Column(db.Text)

    # חסימת מסמכים ברמת החברה (לימור 17/08/2026, בקשת הנהלת החשבונות).
    # חוסמת אישורי פריקה + טופסי מלווה בלבד — הקיימים וכל מה שייכנס בעתיד.
    # ההצהרות ומסמכי ההסכמה נשארים פתוחים תמיד: מסמכים רגולטוריים, לא כלי
    # לחץ מסחרי. שחרור = לחיצה אחת, בלי לגעת בעמודת "הערות למערכת פורטל"
    # בריכוז (זו נשארת החסימה הנקודתית לשורה בודדת).
    # שם קצר לשמות קבצים (לימור 18/08) — ריק = השם המלא בלי בע"מ.
    # נוצר אחרי שכלל "שתי המילים הראשונות" הפיל את "אלביט מערכות סאיקלון"
    # ל-"אלביט מערכות", והתנגש עם "אלביט מערכות כרמיאל" באותה עיר.
    file_short_name = db.Column(db.String(80))

    docs_blocked = db.Column(db.Boolean, default=False)
    docs_blocked_at = db.Column(db.DateTime, nullable=True)
    docs_blocked_by = db.Column(db.String(120), nullable=True)
    docs_blocked_reason = db.Column(db.Text)

    sub_clients = db.relationship("Client", backref=db.backref("parent_client", remote_side="Client.id"), lazy="dynamic")

    def billed_names(self):
        names = [self.name]
        for line in (self.billing_aliases or "").splitlines():
            line = line.strip()
            if line and line not in names:
                names.append(line)
        return names

    def __repr__(self):
        return f"<Client {self.name}>"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    role = db.Column(db.String(50), nullable=False)  # admin / eco_oil_client / eco_depot_client / transport_company
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    email = db.Column(db.String(200), unique=True, nullable=True, index=True)
    # שם איש הקשר (רשות) — לימור 03/09/2026, אחרי מקרה איריס/עמי-חן: השם
    # הודבק לתוך שדה המייל ("איריס - office@...") ושירות המייל דחה את הכתובת.
    # מעכשיו לשם יש מקום משלו, ושדה המייל מקבל כתובת נקייה בלבד.
    contact_name = db.Column(db.String(120), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    # Opt-in Thursday reminder email (Laura's request via Limor, 02/08/2026):
    # a short "your week's documents are in the portal" nudge, no attachments.
    weekly_reminder = db.Column(db.Boolean, default=False)
    # מתי נשלחה למשתמש הזמנת-הפורטל (לימור 19/08) — מוצג בכרטיס כדי לדעת
    # מי כבר הוזמן; שליחה חוזרת מעדכנת את התאריך.
    invited_at = db.Column(db.DateTime, nullable=True)
    # Multi-company user (Limor 02/08/2026): comma-separated ADDITIONAL client
    # ids this login may view (e.g. Laura = both Gadot companies, Shulamit =
    # Gilboa + Beit-El). The portal shows a company switcher; client_id above
    # stays the primary/default company. NOT for same-company spelling
    # variants — those belong in Client.billing_aliases.
    extra_client_ids = db.Column(db.String(200))

    def allowed_client_ids(self):
        """Primary + extra client ids this user may view, primary first."""
        ids = [self.client_id] if self.client_id else []
        for part in (self.extra_client_ids or "").split(","):
            part = part.strip()
            if part.isdigit() and int(part) not in ids:
                ids.append(int(part))
        return ids

    client = db.relationship("Client", backref="users")

    def __repr__(self):
        return f"<User {self.username}>"


class TokenBlocklist(db.Model):
    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MagicLinkToken(db.Model):
    __tablename__ = "magic_link_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    requested_from_ip = db.Column(db.String(45), nullable=True)

    user = db.relationship("User", backref="magic_link_tokens")

    def __repr__(self):
        return f"<MagicLinkToken user={self.user_id} used={self.used_at is not None}>"


class LoginAuditLog(db.Model):
    __tablename__ = "login_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    email_attempted = db.Column(db.String(200), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)  # magic_link_requested / magic_link_verified / password_login / failed_login
    success = db.Column(db.Boolean, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    notes = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User")

    def __repr__(self):
        return f"<LoginAuditLog event={self.event_type} success={self.success}>"


class AdminActionLog(db.Model):
    """יומן פעולות של מסכי הניהול (לימור 06/08/2026, מסך ניהול הדיפו):
    כל פעולה נרשמת על שם מבצעה — 'לימור' / 'משרד דיפו' / 'יואב' (שם התפקיד,
    לא שם האדם — כך המעקב שורד גם החלפת מאיישת), או 'מנהלת ראשית' בכניסת
    סיסמת המאסטר."""
    __tablename__ = "admin_action_log"

    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor = db.Column(db.String(120), nullable=False)
    division = db.Column(db.String(50), nullable=False, index=True)  # eco_depot / eco_oil
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.String(400))

    def __repr__(self):
        return f"<AdminActionLog {self.actor} {self.action}>"


class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(50), nullable=False, unique=True)
    division = db.Column(db.String(50), nullable=False)
    asset_type = db.Column(db.String(20), nullable=False)  # roadtanker / isotank
    status = db.Column(db.String(50), default="confirmed")
    process_stage = db.Column(db.String(50), default="created")

    # לרואדטנקר: כמה תאים יש (ידוע מראש). לאיזוטנק None.
    compartments_count = db.Column(db.Integer)

    def __repr__(self):
        return f"<Asset {self.identifier}>"


class DepotPreArrival(db.Model):
    __tablename__ = "depot_pre_arrivals"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="pre_arrivals")

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    client = db.relationship("Client", backref="pre_arrivals")

    msds_filename = db.Column(db.String(200))
    msds_chemical_name = db.Column(db.String(200))
    msds_manufacturer = db.Column(db.String(200))
    msds_hazard_notes = db.Column(db.Text)
    requested_service = db.Column(db.String(200))
    status = db.Column(db.String(20), default="open")  # open / arrived / closed
    declared_compartments_count = db.Column(db.Integer)
    declared_wash_compartments = db.Column(db.String(50))  # למשל "2" או "1,3"

    def __repr__(self):
        return f"<PreArrival {self.id}>"


class Compartment(db.Model):
    """
    תאים קיימים רק ל-roadtanker.
    number: 1..6
    last_cargo_material: החומר האחרון שהובל בתא (מאומת אצלכם בדיפו)
    """
    __tablename__ = "compartments"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="compartments")

    number = db.Column(db.Integer, nullable=False)  # 1..6
    last_cargo_material = db.Column(db.String(200))
    requested_to_wash = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Compartment asset={self.asset_id} number={self.number}>"


class WashCycle(db.Model):
    __tablename__ = "wash_cycles"
    __table_args__ = (
    db.UniqueConstraint("compartment_id", "cycle_number", name="uq_washcycle_compartment_cycle"),)

    id = db.Column(db.Integer, primary_key=True)

    compartment_id = db.Column(db.Integer, db.ForeignKey("compartments.id"), nullable=False)
    compartment = db.relationship("Compartment", backref="wash_cycles")

    cycle_number = db.Column(db.Integer, nullable=False)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)

    chemical_used = db.Column(db.String(200))
    result = db.Column(db.String(50))  # pass / fail
    notes = db.Column(db.Text)

    # שיטות שטיפה
    wash_hot_water = db.Column(db.Boolean, default=False)
    wash_cold_water = db.Column(db.Boolean, default=False)
    wash_steam = db.Column(db.Boolean, default=False)
    wash_aceton = db.Column(db.Boolean, default=False)
    wash_xylen = db.Column(db.Boolean, default=False)
    wash_detergent = db.Column(db.Boolean, default=False)
    wash_drying = db.Column(db.Boolean, default=False)

    # שירותים נוספים
    service_transportation = db.Column(db.Boolean, default=False)
    service_polish = db.Column(db.Boolean, default=False)
    service_photo_set = db.Column(db.Boolean, default=False)
    service_vacuum_test = db.Column(db.Boolean, default=False)
    service_repair = db.Column(db.Boolean, default=False)
    service_test = db.Column(db.Boolean, default=False)
    service_maintenance = db.Column(db.Boolean, default=False)
    service_storage = db.Column(db.Boolean, default=False)

    checked_by_role = db.Column(db.String(50), default="qc")
    checked_by_name = db.Column(db.String(100))

    def __repr__(self):
        return f"<WashCycle compartment={self.compartment_id} cycle={self.cycle_number}>"

class WashCertificate(db.Model):
    __tablename__ = "wash_certificates"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False, unique=True)
    asset = db.relationship("Asset", backref="wash_certificate")

    issued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    issued_by_name = db.Column(db.String(100), nullable=False)
    issued_by_role = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(50), default="issued", nullable=False)
    
    client_name = db.Column(db.String(200))
    client_address = db.Column(db.String(300))

    last_cargo = db.Column(db.String(200))

    wash_completed_at = db.Column(db.DateTime)

    drying_performed = db.Column(db.Boolean)

    cleaning_details = db.Column(db.Text)
    additional_services = db.Column(db.Text)

    # שדות ייחודיים לאיזוטנק
    total_wash_cycles = db.Column(db.Integer)
    service_transportation = db.Column(db.Boolean)
    service_polish = db.Column(db.Boolean)
    service_repair = db.Column(db.Boolean)
    service_photo_set = db.Column(db.Boolean)
    service_vacuum_test = db.Column(db.Boolean)
    service_storage = db.Column(db.Boolean)
    service_maintenance = db.Column(db.Boolean)
    service_test = db.Column(db.Boolean)
    def __repr__(self):
        return f"<WashCertificate asset={self.asset_id} id={self.id}>"

class TransportEvent(db.Model):
    __tablename__ = "transport_events"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="transport_events")

    direction = db.Column(db.String(20), nullable=False)   # inbound / outbound
    transport_by = db.Column(db.String(20), nullable=False)  # eco_depot / external
    carrier_name = db.Column(db.String(200))  # רלוונטי כש external

    origin = db.Column(db.String(300))
    destination = db.Column(db.String(300))
    transport_date = db.Column(db.DateTime, nullable=False)

    price = db.Column(db.Float)  # רלוונטי רק כש eco_depot
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<TransportEvent asset={self.asset_id} direction={self.direction}>"

class IsotankWashCycle(db.Model):
    __tablename__ = "isotank_wash_cycles"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="isotank_wash_cycles")

    cycle_number = db.Column(db.Integer, nullable=False)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)

    chemical_used = db.Column(db.Text)
    result = db.Column(db.String(50))  # pass / fail
    notes = db.Column(db.Text)

    # שיטות שטיפה
    wash_hot_water = db.Column(db.Boolean, default=False)
    wash_cold_water = db.Column(db.Boolean, default=False)
    wash_steam = db.Column(db.Boolean, default=False)
    wash_aceton = db.Column(db.Boolean, default=False)
    wash_xylen = db.Column(db.Boolean, default=False)
    wash_detergent = db.Column(db.Boolean, default=False)
    wash_drying = db.Column(db.Boolean, default=False)

    # שירותים נוספים
    service_transportation = db.Column(db.Boolean, default=False)
    service_polish = db.Column(db.Boolean, default=False)
    service_photo_set = db.Column(db.Boolean, default=False)
    service_vacuum_test = db.Column(db.Boolean, default=False)
    service_repair = db.Column(db.Boolean, default=False)
    service_test = db.Column(db.Boolean, default=False)
    service_maintenance = db.Column(db.Boolean, default=False)
    service_storage = db.Column(db.Boolean, default=False)

    checked_by_name = db.Column(db.String(100))
    checked_by_role = db.Column(db.String(50), default="qc")

    def __repr__(self):
        return f"<IsotankWashCycle asset={self.asset_id} cycle={self.cycle_number}>"

class RepairEvent(db.Model):
    __tablename__ = "repair_events"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="repair_events")

    description = db.Column(db.Text)
    result = db.Column(db.String(50))  # pass / fail
    checked_by_name = db.Column(db.String(100))
    checked_by_role = db.Column(db.String(50), default="qc")
    price = db.Column(db.Float)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<RepairEvent asset={self.asset_id} result={self.result}>"

class ReleaseDocument(db.Model):
    __tablename__ = "release_documents"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="release_documents")

    client_name = db.Column(db.String(200), nullable=False)
    carrier_name = db.Column(db.String(200))
    carrier_type = db.Column(db.String(20))  # eco_depot / external

    estimated_pickup_date = db.Column(db.DateTime)
    destination = db.Column(db.String(300))

    wash_approved = db.Column(db.Boolean)
    drying_approved = db.Column(db.Boolean)
    is_ready_for_pickup = db.Column(db.Boolean, default=False)

    notes = db.Column(db.Text)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    issued_by_name = db.Column(db.String(100), nullable=False)
    issued_by_role = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f"<ReleaseDocument asset={self.asset_id} id={self.id}>"

class PhotoRecord(db.Model):
    __tablename__ = "photo_records"

    id = db.Column(db.Integer, primary_key=True)

    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id"), nullable=False)
    asset = db.relationship("Asset", backref="photo_records")

    filename = db.Column(db.String(300), nullable=False)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    taken_by = db.Column(db.String(100), nullable=False)
    stage = db.Column(db.String(50))  # pre_wash / post_wash / repair / other
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<PhotoRecord asset={self.asset_id} file={self.filename}>"

# --------------------------
# Eco-Oil Models
# --------------------------

class Carrier(db.Model):
    __tablename__ = "carriers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    business_id = db.Column(db.String(50))  # עוסק מורשה / ח.פ.
    contact_name = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    hazmat_license_number = db.Column(db.String(100))
    hazmat_license_expiry = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<Carrier {self.name}>"


class ProducerDeclaration(db.Model):
    __tablename__ = "producer_declarations"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    client = db.relationship("Client", backref="producer_declarations")

    # פרטי לקוח
    producer_name = db.Column(db.String(200))     # שם העסק/המפעל כפי שהוצהר (יכול להיות שונה משם חשבון הלקוח)
    client_address = db.Column(db.String(300))
    business_id = db.Column(db.String(50))        # מספר ח.פ.
    permit_number = db.Column(db.String(100))      # מספר היתר רעלים
    ceo_name = db.Column(db.String(100))           # שם מנכ"ל / אחראי היתר
    client_email = db.Column(db.String(200))       # מייל
    addressed_to = db.Column(db.String(200))       # מכותב
    producer_size = db.Column(db.String(20))       # קטן / גדול

    # פרטי זרם
    material_name = db.Column(db.String(200), nullable=False)
    material_classification = db.Column(db.String(100))  # english: mineral / emulsion / acid / base / washwater / gasoil
    waste_stream_number = db.Column(db.String(50))        # מספר זרם פסולת
    production_facility = db.Column(db.String(300))       # מתקן הייצור
    basel_y_code = db.Column(db.String(200))              # קוד Y
    basel_annexviii_code = db.Column(db.String(300))      # נספח VIII
    basel_h_code = db.Column(db.String(50))               # קוד סיכון H
    un_risk_group = db.Column(db.String(50))              # קבוצת סיכון האו"ם
    european_catalog_code = db.Column(db.String(300))     # סיווג אירופאי
    treatment_facility_type = db.Column(db.String(200))   # מתקן/סוג טיפול
    basel_r_code = db.Column(db.String(100))              # קוד השבה R
    basel_d_code = db.Column(db.String(100))              # קוד טיפול D
    annual_quantity_text = db.Column(db.String(100))      # כמות שנתית כטקסט
    packaging_type = db.Column(db.String(100))            # סוג האריזה
    waste_main_characteristic = db.Column(db.Text)        # מאפיין עיקרי
    pollutant_type = db.Column(db.String(200))            # סוג המזהם
    concentration_range = db.Column(db.String(200))       # טווח ריכוזים

    valid_from = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    # מחזור חיים (לימור 03/08): submitted (הוגשה) → released (אושר הנוסח, בתא
    # הלקוח לחתימה) → approved (אישור סופי אחרי סריקה חתומה). צדדיים:
    # needs_fix (הוחזרה לתיקון עם fix_note) / superseded (הוגשה מחדש אחרי תיקון)
    # / rejected (נפסלה). הצהרה נשמרת is_active=False עד האישור הסופי.
    status = db.Column(db.String(30), default="approved")
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    fix_note = db.Column(db.Text)          # הערות לימור "מה דורש תיקון" (needs_fix)
    released_at = db.Column(db.DateTime)   # מתי שוחרר לתא הלקוח — בסיס ל"כבר X ימים ממתינה לחתימה" (לימור 12/08)

    # הסריקה החתומה (לימור 09/08) — גם צילום טלפון מתקבל, לא רק סריקה;
    # לימור שופטת קריאוּת ברגע האישור הסופי. מוחלף בהעלאה חוזרת עד האישור.
    # deferred — הקובץ עצמו לא נטען בשאילתות רשימה, רק בגישה מפורשת
    signed_scan_data = deferred(db.Column(db.LargeBinary))
    signed_scan_filename = db.Column(db.String(200))
    signed_scan_mime = db.Column(db.String(60))
    signed_scan_at = db.Column(db.DateTime)
    signed_scan_source = db.Column(db.String(20))  # customer / admin (צירוף מווטסאפ)
    approved_at = db.Column(db.DateTime)           # רגע האישור הסופי — הטריגר להזנת המסד

    # הזנה אוטומטית למסד (לימור 10/08, עקרונות 03/08): הגשר המשרדי מושך
    # הצהרות מאושרות וכותב למסד; שני חצאים נפרדים כדי שכשל חלקי מושלם
    # בסיבוב הבא בלי שכפול. masad_note = מה שדורש השלמה ידנית (מתריעים).
    masad_log_at = db.Column(db.DateTime)      # שורה נוספה בגיליון "הצהרות"
    masad_summary_at = db.Column(db.DateTime)  # עודכן/נוסף בגיליון ח.פ.-היתר-תוקף
    masad_note = db.Column(db.Text)

    # תיוק אוטומטי (לימור 12/08): הגשר מתייק את הסריקה החתומה בתיקיית
    # הלקוח על Z: אחרי האישור הסופי; כשל נרשם כהערה ומתריעים במייל.
    scan_filed_at = db.Column(db.DateTime)
    scan_file_note = db.Column(db.Text)

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<ProducerDeclaration client={self.client_id} material={self.material_name}>"

class AgreementDocument(db.Model):
    __tablename__ = "agreement_documents"

    id = db.Column(db.Integer, primary_key=True)
    declaration_id = db.Column(db.Integer, db.ForeignKey("producer_declarations.id"), nullable=False)
    declaration = db.relationship("ProducerDeclaration", backref="agreement_documents")

    # מספר הסכמה קבוע (לימור 12/08): סדרה חדשה שמתחילה ב-1001, נולד ברגע
    # ההפקה ולא משתנה לעולם — בניגוד למספרי השורות בגיליון המסד שנגזרים
    # ממיקום. מודפס על המסמך; מסמך ביטול עתידי מפנה אליו.
    number = db.Column(db.Integer, unique=True, index=True)

    # תיוק אוטומטי (לימור 12/08): הגשר מוריד את המסמך כ-PDF ומתייק
    # בתיקיית הלקוח על Z:; כשל נרשם כהערה ומתריעים במייל.
    filed_at = db.Column(db.DateTime)
    file_note = db.Column(db.Text)

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    issued_by_name = db.Column(db.String(100), nullable=False)
    valid_from = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<AgreementDocument declaration={self.declaration_id}>"


class DisposalEvent(db.Model):
    __tablename__ = "disposal_events"

    id = db.Column(db.Integer, primary_key=True)
    certificate_number = db.Column(db.String(50), nullable=False, unique=True)
    random_code = db.Column(db.String(50))

    event_date = db.Column(db.DateTime, nullable=False)
    exit_time = db.Column(db.Time)

    carrier_id = db.Column(db.Integer, db.ForeignKey("carriers.id"), nullable=True)
    carrier = db.relationship("Carrier", backref="disposal_events")
    carrier_name = db.Column(db.String(200))  # שם חופשי אם לא רשום במערכת
    vehicle_number = db.Column(db.String(50))

    client_name = db.Column(db.String(200))  # שם הלקוח (המקור)
    client_address = db.Column(db.String(300))
    billed_to = db.Column(db.String(200), nullable=False)  # עמודת החיוב

    material_classification = db.Column(db.String(100), nullable=False)
    is_hazardous = db.Column(db.Boolean, default=False)

    weight_entry = db.Column(db.Float)
    weight_exit = db.Column(db.Float)
    weight_net = db.Column(db.Float)
    weight_declared = db.Column(db.Float)

    packaging_type = db.Column(db.String(50))  # ביובית / קוביות
    packaging_count = db.Column(db.Integer)

    notes = db.Column(db.Text)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    client = db.relationship("Client", backref="disposal_events")
    def __repr__(self):
        return f"<DisposalEvent {self.certificate_number}>"


class DisposalCertificate(db.Model):
    __tablename__ = "disposal_certificates"

    id = db.Column(db.Integer, primary_key=True)
    disposal_event_id = db.Column(db.Integer, db.ForeignKey("disposal_events.id"), nullable=False)
    disposal_event = db.relationship("DisposalEvent", backref="disposal_certificate")

    verification_code = db.Column(db.String(50), unique=True)

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    issued_by_name = db.Column(db.String(100), nullable=False)
    sent_at = db.Column(db.DateTime)
    sent_to_email = db.Column(db.String(200))
    notes = db.Column(db.Text)
    

    def __repr__(self):
        return f"<DisposalCertificate event={self.disposal_event_id}>"


# --------------------------
# Eco-Depot portal: read-only snapshots synced FROM EcoDepot.xlsx (the bridge).
# These mirror the workbook at row-grain so the portal screens can read them.
# Never written by the portal UI — only by the bridge sync. Refreshed each cycle.
# --------------------------

class DepotIsotankVisit(db.Model):
    """One isotank visit row, synced from EcoDepot.xlsx sheet 'רישום תנועות איזוטנקים'."""
    __tablename__ = "depot_isotank_visits"

    id = db.Column(db.Integer, primary_key=True)
    visit_no = db.Column(db.String(60), index=True)
    isotank_number = db.Column(db.String(60), index=True)
    company = db.Column(db.String(200), index=True)   # 'חברה / סוכן' — used to scope a customer's data
    billed_to = db.Column(db.String(200))             # 'גורם מחוייב' — who is charged (split-payer)
    last_material = db.Column(db.String(200))
    un_number = db.Column(db.String(50))
    hazard_class = db.Column(db.String(50))
    status = db.Column(db.String(80))                 # 'סטטוס' — the service step (שלב טיפול)
    arrival_date = db.Column(db.Date)                 # 'תאריך הגעה'
    storage_in_date = db.Column(db.Date)              # 'תאריך כניסה לאחסון'
    storage_out_date = db.Column(db.Date)             # 'תאריך יציאה מאחסון'
    exit_site_date = db.Column(db.Date)               # 'תאריך יציאה מהאתר'
    storage_days = db.Column(db.Integer)              # 'סהכ ימי אחסנה'
    daily_rate = db.Column(db.Float)                  # 'תעריף יומי'
    storage_total = db.Column(db.Float)               # 'סהכ אחסון'
    wash_date = db.Column(db.Date)                    # 'תאריך שטיפה'
    wash_total = db.Column(db.Float)                  # 'סהכ שטיפה'
    entry_hour = db.Column(db.String(20))            # 'שעת כניסה'
    exit_hour = db.Column(db.String(20))             # 'שעת יציאה'
    source_row = db.Column(db.Integer)               # Excel row in the live iso sheet (fast lookup)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DepotIsotankVisit {self.isotank_number} company={self.company}>"


class DepotRoadtankerVisit(db.Model):
    """One roadtanker visit, synced from EcoDepot.xlsx sheet 'רישום תנועות רואדטנקרים'."""
    __tablename__ = "depot_roadtanker_visits"

    id = db.Column(db.Integer, primary_key=True)
    visit_no = db.Column(db.String(60), index=True)
    tanker_number = db.Column(db.String(60), index=True)   # 'מספר מכלית'
    company = db.Column(db.String(200), index=True)
    billed_to = db.Column(db.String(200))
    entry_date = db.Column(db.Date)
    entry_hour = db.Column(db.String(20))
    exit_date = db.Column(db.Date)
    exit_hour = db.Column(db.String(20))
    last_material = db.Column(db.String(200))
    compartment_materials = db.Column(db.String(400))      # joined 'חומר תא 1..6'
    group = db.Column(db.String(80))                       # 'קבוצת רואדטנקר'
    un_number = db.Column(db.String(50))
    hazard_class = db.Column(db.String(50))
    compartments_used = db.Column(db.Integer)
    cert_status = db.Column(db.String(80))                 # 'סטטוס תעודה'
    repairs_note = db.Column(db.String(300))
    wash_total = db.Column(db.Float)
    final_total = db.Column(db.Float)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DepotRoadtankerVisit {self.tanker_number} company={self.company}>"


class DepotStorageCharge(db.Model):
    """Monthly storage charge per tank, from sheet 'חיוב_אחסנה_חודשי' (item 17)."""
    __tablename__ = "depot_storage_charges"

    id = db.Column(db.Integer, primary_key=True)
    visit_no = db.Column(db.String(60), index=True)
    isotank_number = db.Column(db.String(60), index=True)
    company = db.Column(db.String(200), index=True)
    billed_to = db.Column(db.String(200))
    billing_month = db.Column(db.Date)
    storage_days = db.Column(db.Integer)
    daily_rate = db.Column(db.Float)
    total = db.Column(db.Float)
    billing_status = db.Column(db.String(80))
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DepotStorageCharge {self.isotank_number} month={self.billing_month}>"


class DepotRepair(db.Model):
    """Repair line, from sheet 'תיקונים' (feeds the reports תיקונים option)."""
    __tablename__ = "depot_repairs"

    id = db.Column(db.Integer, primary_key=True)
    repair_id = db.Column(db.String(60), index=True)
    visit_no = db.Column(db.String(60), index=True)
    isotank_number = db.Column(db.String(60), index=True)
    repair_date = db.Column(db.Date)
    repair_name = db.Column(db.String(200))
    qty = db.Column(db.Float)
    unit_price = db.Column(db.Float)
    line_total = db.Column(db.Float)
    billed_to = db.Column(db.String(200))                  # 'מי מחויב'
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DepotRepair {self.repair_id} tank={self.isotank_number}>"

# ---------------------------------------------------------------------------
# Eco-Oil unload certificates (אישורי פריקה) — snapshot synced from the office
# ריכוז workbook (Z:\Eco_General\ריכוז חודשי\<year>\ריכוז*_pivot.xlsx).
# One row per unload event = one certificate. The ריכוז is the source of
# truth; this table is a read-only WINDOW onto it (wiped+reloaded per sync).
# ---------------------------------------------------------------------------

class EcoOilUnloadEvent(db.Model):
    """One unload event (= one אישור פריקה) from a monthly ריכוז sheet."""
    __tablename__ = "ecooil_unload_events"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, index=True, nullable=False)
    month = db.Column(db.Integer, index=True, nullable=False)
    serial = db.Column(db.Integer)                          # מס' תעודה (per-month serial)
    code = db.Column(db.String(20), index=True)             # קוד_רנדומלי (e.g. JUL010104)
    event_date = db.Column(db.Date, index=True)             # תאריך
    vehicle = db.Column(db.String(40))                      # מספר הרכב
    transporter = db.Column(db.String(200), index=True)     # חברת ההובלה
    customer = db.Column(db.String(200), index=True)        # לקוח = producer/source
    address = db.Column(db.String(200))                     # כתובת
    billed_to = db.Column(db.String(200), index=True)       # חיוב
    stream = db.Column(db.String(60), index=True)           # סיווג החומר (as written)
    stream_norm = db.Column(db.String(30), index=True)      # canonical stream for filtering (dictionary approved 2026-07-14)
    weight_in = db.Column(db.Float)                         # משקל כניסה
    weight_out = db.Column(db.Float)                        # משקל יציאה
    weight_net = db.Column(db.Float)                        # משקל נטו
    declared_tons = db.Column(db.Float)                     # משקל מוצהר (tons)
    package_type = db.Column(db.String(60))                 # סוג אריזה
    package_count = db.Column(db.Integer)                   # מס' אריזות
    exit_time = db.Column(db.String(20))                    # שעת יציאה
    notes = db.Column(db.String(400))                       # הערות
    # doc_status: NULL = normal (certificate expected); 'awaiting_declaration' =
    # certificate withheld until the producer declaration is settled (the sanction,
    # shown prominently in the portal); 'no_cert_by_design' = documentation-only
    # row (destruction / empty packaging) — no certificate ever exists;
    # 'unpublished' = Limor's "לא לפרסם" — docs withheld with no explanation
    # (set via the ריכוז column "הערות למערכת פורטל", which overrides the
    # note-based classification).
    doc_status = db.Column(db.String(30), index=True)
    # filed_owner: the filing-folder chain of the matched certificate under
    # Z:\Eco_General (e.g. 'מיקוש שאיבות' or 'גדות_כולל / גדות אחסון ושינוע'),
    # derived server-side from pdf_path at sync. Limor's ruling 06/08/2026:
    # WHERE THE CERTIFICATE IS FILED is the portal-visibility anchor; the
    # billed column is only the fallback (no file / folder not recognized).
    filed_owner = db.Column(db.String(200), index=True)
    pdf_path = db.Column(db.String(400))                    # matched filed PDF (filled by matcher)
    pdf_key = db.Column(db.String(500))                     # B2 object key (cloud copy of the PDF)
    manifest_path = db.Column(db.String(400))               # matched signed טופס מלווה scan (matcher)
    manifest_key = db.Column(db.String(500))                # B2 object key of the manifest scan
    source_sheet = db.Column(db.String(40))
    source_row = db.Column(db.Integer)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<EcoOilUnloadEvent {self.event_date} {self.stream} {self.customer}>"

# ---------------------------------------------------------------------------
# Field terminals (מסופוני שטח) — capture layer: events + photos relayed
# from the yard tablets to the office bridge. The cloud only STORES;
# all decisions (OCR validation, Excel posting, photo filing) happen
# at the office bridge. Photos are purged once the bridge acks.
# ---------------------------------------------------------------------------

class FieldDevice(db.Model):
    """A tablet assigned to a yard worker. Token = bearer auth for the terminal API."""
    __tablename__ = "field_devices"

    id = db.Column(db.Integer, primary_key=True)
    worker_name = db.Column(db.String(120), nullable=False)   # שם העובד — נרשם על כל אירוע
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<FieldDevice {self.worker_name}>"


class FieldEvent(db.Model):
    """One physical event captured in the yard: entry / wash / exit (+repairs in v2)."""
    __tablename__ = "field_events"

    id = db.Column(db.Integer, primary_key=True)
    client_uuid = db.Column(db.String(40), unique=True, nullable=False, index=True)  # idempotency
    device_id = db.Column(db.Integer, db.ForeignKey("field_devices.id"), nullable=False)
    worker_name = db.Column(db.String(120), nullable=False)
    event_type = db.Column(db.String(20), nullable=False)     # entry | wash | exit
    asset_type = db.Column(db.String(10), nullable=False)     # iso | rt
    tank_number = db.Column(db.String(40))                    # from dropdown, or empty until OCR
    event_at = db.Column(db.DateTime, nullable=False)         # device time of capture
    payload = db.Column(db.Text)                              # JSON: treatments, cells, notes...
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    # pending → fetched (bridge downloaded) → posted (in live file) | error
    bridge_note = db.Column(db.String(400))                   # e.g. decoded tank, error reason
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    posted_at = db.Column(db.DateTime)

    device = db.relationship("FieldDevice")
    photos = db.relationship("FieldPhoto", backref="event", lazy=True)

    def __repr__(self):
        return f"<FieldEvent {self.event_type} {self.tank_number or '?'} {self.status}>"


class FieldPhoto(db.Model):
    """Photo attached to a field event. Bytes purged after the bridge acks."""
    __tablename__ = "field_photos"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("field_events.id"), nullable=False, index=True)
    kind = db.Column(db.String(20), default="photo")          # plate | photo
    filename = db.Column(db.String(200), nullable=False)
    mime = db.Column(db.String(60), default="image/jpeg")
    data = db.Column(db.LargeBinary)                          # purged on ack
    size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FieldOnsiteAsset(db.Model):
    """Snapshot of assets currently on site — feeds the terminal's wash/exit dropdown.
    Replaced wholesale by the bridge on every poll cycle."""
    __tablename__ = "field_onsite_assets"

    id = db.Column(db.Integer, primary_key=True)
    asset_type = db.Column(db.String(10), nullable=False)     # iso | rt
    tank_number = db.Column(db.String(40), nullable=False)
    customer = db.Column(db.String(200))
    status = db.Column(db.String(60))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class FieldBoard(db.Model):
    """The live ops board for the tablets (Damoni 16/07: reports on the tablet
    instead of the printed 14:00 PDF). Single row, JSON blob, replaced wholesale
    by the bridge every cycle — the cloud stores, never computes."""
    __tablename__ = "field_board"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)                                  # JSON: release_prep/release_wait/care/expected
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class DepotPreArrival(db.Model):
    """טופס מידע מקדים (פורטל הדיפו, שלב 1 — לימור 06/08/2026) — המחליף של
    המייל המקדים. הלקוח מגיש בפורטל; הגשר של יעל מושך (אותה תבנית כמו אירועי
    המסופונים: pending → fetched → posted), פותח שורת "בדרך להיכנס" מלאה
    בקובץ החי (חוק 53) ומאשר קליטה. קובץ ה-MSDS נמחק מהענן אחרי הקליטה."""
    __tablename__ = "depot_prearrivals"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    tank_number = db.Column(db.String(40), nullable=False)      # ISO-6346 validated
    material = db.Column(db.String(200), nullable=False)        # החומר האחרון
    un_number = db.Column(db.String(20), nullable=False)
    hazard_class = db.Column(db.String(20), nullable=False)
    carrier = db.Column(db.String(200))                         # מוביל מהרשימה
    carrier_new = db.Column(db.String(200))                     # מוביל חדש (לבדיקת המשרד, חוק 47ג)
    purpose = db.Column(db.String(60), nullable=False)          # שטיפה + אחסנה / אחסנה בלבד / שטיפה בלבד / אחר
    purpose_other = db.Column(db.String(200))
    expected_date = db.Column(db.Date)
    svc_dry = db.Column(db.Boolean, default=False)
    svc_vacuum = db.Column(db.Boolean, default=False)
    svc_photos = db.Column(db.String(60))                       # סוג סט התמונות, ריק=לא הוזמן
    svc_repairs = db.Column(db.String(400))                     # פירוט תיקונים, ריק=לא הוזמן
    internal_ref = db.Column(db.String(100))                    # "מספרנו"
    emergency_phone = db.Column(db.String(60))
    notes = db.Column(db.String(400))

    msds_filename = db.Column(db.String(200))
    msds_mime = db.Column(db.String(60))
    msds_size = db.Column(db.Integer)
    msds_data = db.Column(db.LargeBinary)                       # purged on ack

    # "גורם מחוייב" לפי הצהרת הלקוח (לימור 24/08) — 4 הפרמטרים כמו בקובץ.
    # הצהרה בלבד: זורמת כהערה למשרד (AF דרך צינור ההערות של הגשר), לעולם
    # לא ישירות לעמודות החיוב — אלה נקבעות במשרד לפי ההסכמים.
    payer_storage = db.Column(db.String(120))
    payer_wash = db.Column(db.String(120))
    payer_extras = db.Column(db.String(120))    # הנפות · תמונות · ואקום
    payer_repairs = db.Column(db.String(120))   # תיקונים · הובלה

    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    # pending → fetched (bridge downloaded) → posted (צפי row born) | error
    bridge_note = db.Column(db.String(400))
    posted_at = db.Column(db.DateTime)

    client = db.relationship("Client")


class EcoOilValiditySnapshot(db.Model):
    """תמונת גיליון ח.פ.-היתר-תוקף מהמסד (לימור 03/09/2026): מקור האמת לרשימת
    לקוחות החומ"ס של כל מוביל הוא עמודת "סוג לקוח" בגיליון — לא הצהרות הענן.
    שורה יחידה, JSON, נדחפת ע"י הגשר בסבב השעתי (ecooil_validity_push.py) —
    המשרד נשאר מקור האמת; הענן רק מציג. rows: [{referrer,name,hp,streams}]."""
    __tablename__ = "ecooil_validity_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class EcoOilFilingRuling(db.Model):
    """תשובת לימור לסתירת תיוק-מול-חיוב (03/09/2026): במקום מייל/תיקון ידני,
    היא עונה ישירות בטבלת הסתירות במסך הניהול. המפתח = הצמד המדויק
    (עמודת החיוב, תיקיית התיוק) — כך התשובה שורדת כל סנכרון שעתי וחלה גם על
    שורות עתידיות של אותו צמד. התשובה עונה על שאלה אחת: למי שייכים האישורים —
    decision: 'folder' (לחברת התיקייה — התצוגה ממילא לפי התיקייה) /
    'billed' (לגורם שבעמודת החיוב — עוקף את עוגן-התיקייה לצמד; גורם לא רשום
    יופיע אוטומטית ברגע שיוקם לו כרטיס, כי שיפוט-החיוב הוא לפי שם+כתיבים) /
    'client' + client_id (לחברה אחרת שבחרה — הצמד מוצג אצלה בלבד; 03/09 ערב,
    אחרי משוב ש.צ.פ/עידן וצ.כץ/הגליל: השליטה כולה אצלה)."""
    __tablename__ = "ecooil_filing_rulings"

    id = db.Column(db.Integer, primary_key=True)
    billed_to = db.Column(db.Text, nullable=False)
    filed_owner = db.Column(db.Text, nullable=False)
    decision = db.Column(db.String(20), nullable=False)   # folder / billed / client
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    actor = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DepotFormOptions(db.Model):
    """רשימות הבחירה של טופס המידע המקדים — חומרים (מהמסד) + מובילים
    (CARRIER_OPTIONS, חוק 47ג). שורה יחידה, JSON, נדחפת ע"י הגשר בכל סבב —
    מקור האמת נשאר במשרד; הענן רק מציג."""
    __tablename__ = "depot_form_options"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)                                   # JSON: {materials:[], carriers:[]}
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


class DepotWashCert(db.Model):
    """תעודות שטיפה בפורטל הדיפו (שלב 2 במפת הדרכים — לימור 23/08/2026).
    כל שורה = קובץ PDF אחד בתיקיות O:\\SHTIFOT\\תעודות שטיפה. הסקריפט השעתי
    במחשב של לימור סורק (קריאה בלבד, 2026 ואילך — הכרעתה), מעלה ל-B2 ודוחף
    לכאן. העוגן = תיקיית התיוק (הכרעת 06/08): folder נפתר לכרטיס חברה לפי
    שם+כתיבים בזמן שאילתה — תיקייה לא מזוהה לא מוצגת לאיש, רק במסך הניהול."""
    __tablename__ = "depot_wash_certs"

    id = db.Column(db.Integer, primary_key=True)
    b2_key = db.Column(db.String(500), unique=True, nullable=False, index=True)
    folder = db.Column(db.String(200), nullable=False, index=True)   # תיקיית הלקוח ברמה העליונה
    tank = db.Column(db.String(40), index=True)                      # מספר המכל (מהתיקייה/שם הקובץ)
    year = db.Column(db.Integer, index=True)
    month = db.Column(db.Integer)                                    # חודש הביקור = חודש הכניסה (חוק 8)
    file_name = db.Column(db.String(300), nullable=False)
    file_date = db.Column(db.DateTime, index=True)                   # חותמת הקובץ בדיסק
    size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # הסיכום היומי (הכרעת 23/08): NULL = טרם נכלל בסיכום; ההטענה ההיסטורית
    # הראשונית מוחתמת מיד כדי שהמייל הראשון לא יספור מאות תעודות ישנות.
    notified_at = db.Column(db.DateTime)


class DepotAssetSnapshot(db.Model):
    """"הנכסים שלי אצלכם" (שלב 3 במפת הדרכים — אישור יואב 02/09/2026).
    תמונת-מצב של הנכסים הנמצאים באתר, מהסבב השעתי במחשב של לימור (קריאה
    בלבד מעותק של הקובץ החי) — החלפה מלאה בכל דחיפה. השיוך ללקוח נפתר
    בזמן שאילתה לפי "גורם מחוייב אחסנה" מול שם+כתיבים (עוגן הכתיבים,
    כמו התעודות) — ערך לא מזוהה לא מוצג לאף לקוח."""
    __tablename__ = "depot_asset_snapshots"
    # ⚠ העוגן = מס' ביקור + מכל יחד: בקובץ יש מספרי ביקור כפולים מהעבר
    # (מלפני הקפאת המספרים 15/07) — מכלים שונים שחולקים מספר. התגלה 02/09
    # בדחיפה הראשונה (14 מספרים כפולים, 26 מכלים).
    __table_args__ = (db.UniqueConstraint("visit_id", "tank",
                                          name="uq_depot_asset_visit_tank"),)

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.String(40), nullable=False, index=True)  # מס' ביקור
    tank = db.Column(db.String(40), nullable=False, index=True)
    storage_payer = db.Column(db.String(200), index=True)       # גורם מחוייב אחסנה (D) — עוגן השיוך
    status = db.Column(db.String(40), nullable=False)           # הסטטוס בקובץ (I), כלשונו
    material = db.Column(db.String(200))                        # חומר אחרון (F)
    arrival_date = db.Column(db.Date)                           # תאריך הגעה (J, ובהיעדרה R)
    est_exit_date = db.Column(db.Date)                          # תאריך משוער ליציאה (AK)
    pushed_at = db.Column(db.DateTime, nullable=False)          # מתי נדחפה התמונה
    # המסך המשולב — פס "מה קרה אצלכם" + ציר זמן לנכס (אישור יואב 04/09/2026).
    # שעות כמחרוזות HH:MM בכוונה (לקח עיוות אזור-הזמן של pywin32, 04/09).
    entry_time = db.Column(db.String(5))                        # שעת כניסה לאחסון (AI)
    wash_date = db.Column(db.Date)                              # תאריך שטיפה (L)
    wash_time = db.Column(db.String(5))                         # שעת שטיפה (M)
    exit_date = db.Column(db.Date)                              # יציאה (S ואם ריק K) — רק ביציאות טריות
    exit_time = db.Column(db.String(5))                         # שעת יציאה (AJ)
    exited = db.Column(db.Boolean, default=False, nullable=False)  # יציאה טרייה: בפס האירועים, לא בטבלה


class DepotReleaseRequest(db.Model):
    """בקשת שחרור / ביטול שחרור מהפורטל (אישור יואב 02/09/2026, בעקבות
    שאלת אלירן-טנקו). אותו עיקרון כמו הטופס המקדים: הלקוח מבקש — הגשר של
    יעל מושך, מעדכן סטטוס בקובץ החי ומאשר. כלל לימור: ביטול אפשרי רק כל
    עוד העובד לא סימן בטאבלט "מוכן לשחרור"; הגשר בודק שוב ברגע הביצוע."""
    __tablename__ = "depot_release_requests"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    visit_id = db.Column(db.String(40), nullable=False, index=True)  # מס' הביקור מהתמונה
    tank = db.Column(db.String(40), nullable=False)
    action = db.Column(db.String(10), nullable=False)           # release / cancel
    requested_date = db.Column(db.Date)                         # תאריך איסוף מבוקש (בשחרור)
    carrier = db.Column(db.String(200))                         # מוביל אוסף (רשות)
    notes = db.Column(db.String(400))

    # pending → fetched (הגשר משך) → posted (הסטטוס עודכן בקובץ) /
    # rejected (נפסל בבדיקת-האמת — למשל כבר סומן מוכן) / error
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    bridge_note = db.Column(db.String(400))
    posted_at = db.Column(db.DateTime)

    client = db.relationship("Client")


class FieldInstructions(db.Model):
    """Phase-3 instructions engine (Yoav's rules 19/07): per-tank wash type,
    PPE level and material, keyed by tank number. Single row, JSON blob,
    replaced wholesale by the bridge every cycle (same pattern as FieldBoard)."""
    __tablename__ = "field_instructions"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)                                  # JSON: {tank: {wash, ppe, ppe_level, material}}
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
