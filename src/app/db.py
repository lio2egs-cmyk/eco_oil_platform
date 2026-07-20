from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    division = db.Column(db.String(50), nullable=False)  # eco_oil / eco_depot
    client_type = db.Column(db.String(50))  # direct / indirect / agent
    parent_client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)

    sub_clients = db.relationship("Client", backref=db.backref("parent_client", remote_side="Client.id"), lazy="dynamic")

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
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

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

    # מחזור חיים: submitted (הוגשה בפורטל, ממתינה לחתימה+אישור) / approved (אושרה).
    # הצהרה שהוגשה בפורטל נשמרת is_active=False עד שאקו-אויל מאשרת אותה.
    status = db.Column(db.String(30), default="approved")
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<ProducerDeclaration client={self.client_id} material={self.material_name}>"

class AgreementDocument(db.Model):
    __tablename__ = "agreement_documents"

    id = db.Column(db.Integer, primary_key=True)
    declaration_id = db.Column(db.Integer, db.ForeignKey("producer_declarations.id"), nullable=False)
    declaration = db.relationship("ProducerDeclaration", backref="agreement_documents")

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
    # row (destruction / empty packaging) — no certificate ever exists.
    doc_status = db.Column(db.String(30), index=True)
    pdf_path = db.Column(db.String(400))                    # matched filed PDF (filled by matcher)
    pdf_key = db.Column(db.String(500))                     # B2 object key (cloud copy of the PDF)
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


class FieldInstructions(db.Model):
    """Phase-3 instructions engine (Yoav's rules 19/07): per-tank wash type,
    PPE level and material, keyed by tank number. Single row, JSON blob,
    replaced wholesale by the bridge every cycle (same pattern as FieldBoard)."""
    __tablename__ = "field_instructions"

    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text)                                  # JSON: {tank: {wash, ppe, ppe_level, material}}
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
