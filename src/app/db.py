from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Client(db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    division = db.Column(db.String(50), nullable=False)  # eco_oil / eco_depot
    client_type = db.Column(db.String(50))  # direct / indirect / agent

    def __repr__(self):
        return f"<Client {self.name}>"


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

    material_name = db.Column(db.String(200), nullable=False)
    material_classification = db.Column(db.String(100))  # בסיס / אמולסיה / מי שטיפה / מינרלי / חומצה
    basel_code = db.Column(db.String(50))  # קוד באזל
    annual_quantity_tons = db.Column(db.Float)

    valid_from = db.Column(db.DateTime, nullable=False)
    valid_until = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

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