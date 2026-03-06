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