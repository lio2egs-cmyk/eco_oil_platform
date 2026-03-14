from flask import Blueprint, request
from datetime import datetime
import secrets
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
from .db import db, Client, DepotPreArrival, Asset, Compartment, WashCycle, WashCertificate, TransportEvent, IsotankWashCycle, RepairEvent, ReleaseDocument, PhotoRecord, Carrier, DisposalEvent, DisposalCertificate, ProducerDeclaration

main = Blueprint("main", __name__)


@main.route("/")
def home():
    return "Eco-Oil Platform is running."


# ------------------------
# Clients
# ------------------------
@main.route("/clients", methods=["POST"])
def create_client():
    data = request.get_json() or {}

    client = Client(
        name=data["name"],
        division=data["division"],
        client_type=data.get("client_type"),
    )

    db.session.add(client)
    db.session.commit()

    return {"message": "Client created successfully", "client_id": client.id}, 201


@main.route("/clients", methods=["GET"])
def list_clients():
    clients = Client.query.order_by(Client.id).all()
    return {
        "clients": [
            {
                "id": c.id,
                "name": c.name,
                "division": c.division,
                "client_type": c.client_type,
            }
            for c in clients
        ]
    }, 200


# ------------------------
# Assets
# ------------------------
@main.route("/assets", methods=["POST"])
def create_asset():
    data = request.get_json() or {}

    asset_type = data.get("asset_type")
    allowed_types = {"roadtanker", "isotank"}
    if asset_type not in allowed_types:
        return {"error": f"asset_type must be one of {sorted(list(allowed_types))}"}, 400

    compartments_count = data.get("compartments_count")
    if asset_type == "roadtanker" and compartments_count is not None:
        try:
            compartments_count = int(compartments_count)
        except Exception:
            return {"error": "compartments_count must be an integer"}, 400
        if not (1 <= compartments_count <= 6):
            return {"error": "compartments_count must be between 1 and 6"}, 400

    if asset_type == "isotank":
        compartments_count = None  # לאיזוטנק אין תאים

    asset = Asset(
        identifier=data["identifier"],
        division=data["division"],
        asset_type=asset_type,
        compartments_count=compartments_count,
        process_stage="created"
    )

    db.session.add(asset)
    db.session.commit()

    return {"message": "Asset created successfully", "asset_id": asset.id}, 201


@main.route("/assets", methods=["GET"])
def list_assets():
    status = request.args.get("status")
    asset_type = request.args.get("asset_type")
    process_stage = request.args.get("process_stage")

    query = Asset.query
    if status:
        query = query.filter_by(status=status)
    if asset_type:
        query = query.filter_by(asset_type=asset_type)
    if process_stage:
        query = query.filter_by(process_stage=process_stage)

    assets = query.order_by(Asset.id).all()
    return {
        "assets": [
            {
                "id": a.id,
                "identifier": a.identifier,
                "division": a.division,
                "asset_type": a.asset_type,
                "status": a.status,
                "process_stage": a.process_stage,
                "compartments_count": a.compartments_count,
            }
            for a in assets
        ]
    }, 200


# ------------------------
# Pre-Arrivals
# ------------------------
@main.route("/pre-arrivals", methods=["POST"])
def create_pre_arrival():
    data = request.get_json() or {}

    asset_identifier = data.get("asset_identifier")
    if not asset_identifier:
        return {"error": "asset_identifier is required"}, 400

    declared_compartments_count = data.get("declared_compartments_count")
    declared_wash_compartments = data.get("declared_wash_compartments")  # "2" / "1,3" / None

    asset = Asset.query.filter_by(identifier=asset_identifier).first()
    if not asset:
        asset_type = data.get("asset_type")
        if asset_type not in {"roadtanker", "isotank"}:
            return {
                "error": "asset_type is required and must be 'roadtanker' or 'isotank' when creating a new asset"
            }, 400

        asset = Asset(
            identifier=asset_identifier,
            division="eco_depot",
            asset_type=asset_type,
            status="confirmed",
            process_stage="created",
            compartments_count=None,  # בפועל נקבע בעמדת שטיפה (B)
        )
        db.session.add(asset)
        db.session.commit()

    pre_arrival = DepotPreArrival(
        asset_id=asset.id,
        client_id=data["client_id"],
        msds_filename=data.get("msds_filename"),
            msds_chemical_name=data.get("msds_chemical_name"),
            msds_manufacturer=data.get("msds_manufacturer"),
            msds_hazard_notes=data.get("msds_hazard_notes"),
            requested_service=data.get("requested_service"),
            declared_compartments_count=declared_compartments_count,
            declared_wash_compartments=declared_wash_compartments,
        )

    db.session.add(pre_arrival)
    db.session.commit()

    return {
        "message": "PreArrival created successfully",
        "pre_arrival_id": pre_arrival.id,
        "asset_id": asset.id,
    }, 201


@main.route("/pre-arrivals", methods=["GET"])
def list_pre_arrivals():
    rows = DepotPreArrival.query.order_by(DepotPreArrival.id).all()
    return {
        "pre_arrivals": [
            {
                "id": r.id,
                "asset_id": r.asset_id,
                "client_id": r.client_id,
                "msds_filename": r.msds_filename,
                "msds_chemical_name": r.msds_chemical_name,
                "msds_manufacturer": r.msds_manufacturer,
                "msds_hazard_notes": r.msds_hazard_notes,
                "requested_service": r.requested_service,
                "declared_compartments_count": r.declared_compartments_count,
                "declared_wash_compartments": r.declared_wash_compartments,
                "asset_status": r.asset.status if r.asset else None,
                "asset_process_stage": r.asset.process_stage if r.asset else None,
                "asset_type": r.asset.asset_type if r.asset else None,
                "asset_compartments_count": r.asset.compartments_count if r.asset else None,
            }
            for r in rows
        ]
    }, 200


@main.route("/pre-arrivals/<int:pre_arrival_id>/arrive", methods=["PATCH"])
def mark_pre_arrival_arrived(pre_arrival_id):
    pre = DepotPreArrival.query.get(pre_arrival_id)
    if not pre:
        return {"error": "PreArrival not found"}, 404

    asset = Asset.query.get(pre.asset_id)
    if not asset:
        return {"error": "Asset not found for this PreArrival"}, 404

    asset.status = "arrived"
    if asset.asset_type == "roadtanker":
        asset.process_stage = "waiting"
    else:
        asset.process_stage = "arrived"
    db.session.commit()

    return {
        "message": "Arrived: asset moved to waiting",
        "pre_arrival": {"id": pre.id, "asset_id": pre.asset_id, "client_id": pre.client_id},
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "process_stage": asset.process_stage,
            "compartments_count": asset.compartments_count,
        },
    }, 200


# ------------------------
# Compartments (רק ל-roadtanker)
# ------------------------
@main.route("/assets/<int:asset_id>/compartments/setup", methods=["PATCH"])
def setup_roadtanker_compartments(asset_id):
    """
    שלב עמדת שטיפה (B):
    - מעדכן Asset.compartments_count (המספר בפועל אחרי בדיקה)
    - יוצר אוטומטית Compartment 1..N אם עדיין לא קיימים
    - מעדכן requested_to_wash לפי declared_wash_compartments מה-PreArrival האחרון:
        * אם אין הצהרה -> כל התאים True
        * אם יש הצהרה -> רק התאים המוצהרים True, כל השאר False
    """
    data = request.get_json() or {}
    count = data.get("compartments_count")

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "roadtanker":
        return {"error": "Compartments setup is only for roadtanker assets"}, 400

    try:
        count = int(count)
    except Exception:
        return {"error": "compartments_count must be an integer"}, 400

    if not (1 <= count <= 6):
        return {"error": "compartments_count must be between 1 and 6"}, 400

    asset.compartments_count = count

    existing_numbers = {c.number for c in asset.compartments}
    created = []
    for n in range(1, count + 1):
        if n not in existing_numbers:
            c = Compartment(asset_id=asset.id, number=n)
            db.session.add(c)
            created.append(n)
    db.session.flush()

    # fetch latest pre-arrival for this asset
    latest_pre = (
        DepotPreArrival.query
        .filter_by(asset_id=asset.id)
        .order_by(DepotPreArrival.id.desc())
        .first()
    )

    declared = (latest_pre.declared_wash_compartments if latest_pre else None)
    declared = declared.strip() if declared else None
    print("DEBUG declared:", declared)

    requested_set = None
    if declared:
        try:
            requested_set = {int(x.strip()) for x in declared.split(",") if x.strip()}
        except Exception:
            return {
                "error": "declared_wash_compartments must be a comma-separated list of numbers (e.g. '2' or '1,3')",
                "declared_wash_compartments": declared,
            }, 400

    for c in asset.compartments:
        if requested_set is None:
            c.requested_to_wash = True
        else:
            c.requested_to_wash = (c.number in requested_set)

    db.session.commit()

    return {
        "message": "Compartments setup completed",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "compartments_count": asset.compartments_count,
        },
        "created_compartment_numbers": created,
        "compartments": [
            {
                "id": c.id,
                "number": c.number,
                "last_cargo_material": c.last_cargo_material,
                "requested_to_wash": c.requested_to_wash,
            }
            for c in sorted(asset.compartments, key=lambda x: x.number)
        ],
        "declared_wash_compartments": declared if declared else None,
    }, 200


@main.route("/assets/<int:asset_id>/compartments", methods=["GET"])
def list_compartments(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    return {
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "asset_type": asset.asset_type,
        },
        "compartments": [
            {
                "id": c.id,
                "number": c.number,
                "last_cargo_material": c.last_cargo_material,
                "requested_to_wash": c.requested_to_wash,
            }
            for c in sorted(asset.compartments, key=lambda x: x.number)
        ],
    }, 200


# ------------------------
# Wash Cycles (לפי תא)
# ------------------------
@main.route("/assets/<int:asset_id>/compartments/<int:number>/wash-cycles", methods=["POST"])
def start_wash_cycle(asset_id, number):
    data = request.get_json() or {}

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "roadtanker":
        return {"error": "Wash cycles by compartment are only for roadtanker (isotank will be handled separately later)"}, 400

    comp = Compartment.query.filter_by(asset_id=asset_id, number=number).first()
    if not comp:
        return {"error": f"Compartment {number} not found for this asset. Run /assets/{asset_id}/compartments/setup first."}, 404

    # Hard rule: cannot start wash on a compartment that wasn't requested
    if comp.requested_to_wash is False:
        latest_pre = (
            DepotPreArrival.query
            .filter_by(asset_id=asset.id)
            .order_by(DepotPreArrival.id.desc())
            .first()
        )
        declared = (latest_pre.declared_wash_compartments if latest_pre else None)
        declared = (declared or "").strip()

        return {
            "error": f"Compartment {number} was not requested to wash (declared_wash_compartments='{declared}')",
            "declared_wash_compartments": declared if declared else None,
        }, 400

    last_cycle = (
        WashCycle.query.filter_by(compartment_id=comp.id)
        .order_by(WashCycle.cycle_number.desc())
        .first()
    )
    next_num = 1 if not last_cycle else last_cycle.cycle_number + 1

    cycle = WashCycle(
        compartment_id=comp.id,
        cycle_number=next_num,
        chemical_used=data.get("chemical_used"),
        notes=data.get("notes"),
    )
    db.session.add(cycle)

    asset.process_stage = "washing"
    db.session.commit()

    return {
        "message": "Wash cycle started",
        "asset": {"id": asset.id, "process_stage": asset.process_stage, "status": asset.status},
        "compartment": {"id": comp.id, "number": comp.number, "requested_to_wash": comp.requested_to_wash},
        "wash_cycle": {
            "id": cycle.id,
            "compartment_id": cycle.compartment_id,
            "cycle_number": cycle.cycle_number,
            "chemical_used": cycle.chemical_used,
            "notes": cycle.notes,
            "started_at": cycle.started_at,
        },
    }, 201


@main.route("/wash-cycles/<int:cycle_id>/finish", methods=["PATCH"])
def finish_wash_cycle(cycle_id):
    data = request.get_json() or {}

    cycle = WashCycle.query.get(cycle_id)
    if not cycle:
        return {"error": "Wash cycle not found"}, 404

    cycle.result = data.get("result")  # pass / fail
    cycle.ended_at = db.func.now()
    cycle.notes = data.get("notes", cycle.notes)

    cycle.checked_by_role = data.get("checked_by_role", cycle.checked_by_role)
    cycle.checked_by_name = data.get("checked_by_name", cycle.checked_by_name)

        # אם זה roadtanker – לבדוק האם כל התאים שנדרשו לשטיפה עברו PASS
    asset = cycle.compartment.asset

    if asset and asset.asset_type == "roadtanker":
        requested_comps = [c for c in asset.compartments if c.requested_to_wash]

        all_passed = True
        for c in requested_comps:
            last_cycle = (
                WashCycle.query.filter_by(compartment_id=c.id)
                .order_by(WashCycle.cycle_number.desc())
                .first()
            )

            if not last_cycle or last_cycle.result != "pass":
                all_passed = False
                break

        if all_passed:
            asset.status = "ready_for_release"
            asset.process_stage = "ready_for_release"

            db.session.commit()

    return {
        "message": "Wash cycle finished",
        "wash_cycle": {
            "id": cycle.id,
            "compartment_id": cycle.compartment_id,
            "cycle_number": cycle.cycle_number,
            "result": cycle.result,
            "started_at": cycle.started_at,
            "ended_at": cycle.ended_at,
            "checked_by_role": cycle.checked_by_role,
            "checked_by_name": cycle.checked_by_name,
        },
    }, 200

@main.route("/assets/<int:asset_id>/ready-for-release", methods=["PATCH"])
def mark_ready_for_release(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    # כרגע אנחנו מיישמים את זה רק ל-roadtanker
    if asset.asset_type != "roadtanker":
        return {"error": "ready-for-release is currently implemented only for roadtanker"}, 400

    # חייבים תאים מוגדרים
    if not asset.compartments or not asset.compartments_count:
        return {"error": "No compartments found. Run /assets/<id>/compartments/setup first."}, 400

    # בודקים רק תאים שהלקוח ביקש לשטוף (או ברירת מחדל: כולם True)
    to_check = [c for c in asset.compartments if getattr(c, "requested_to_wash", True) is True]

    if not to_check:
        return {"error": "No compartments marked as requested_to_wash=True"}, 400

    problems = []
    for c in to_check:
        last_cycle = (
            WashCycle.query.filter_by(compartment_id=c.id)
            .order_by(WashCycle.cycle_number.desc())
            .first()
        )
        if not last_cycle:
            problems.append({"compartment": c.number, "error": "no wash cycles found"})
            continue

        if last_cycle.result != "pass" or last_cycle.ended_at is None:
            problems.append({
                "compartment": c.number,
                "error": "last cycle is not a completed PASS",
                "last_cycle_number": last_cycle.cycle_number,
                "last_cycle_result": last_cycle.result,
                "last_cycle_ended_at": str(last_cycle.ended_at) if last_cycle.ended_at else None,
            })

    if problems:
        return {
            "error": "Not ready for release: some requested compartments are not completed PASS",
            "details": problems,
        }, 400

    # הכל עבר QC -> מוכנים לשחרור (פה בעתיד נחבר הפקת תעודת שטיפה)
    asset.process_stage = "ready_for_release"
    db.session.commit()

    return {
        "message": "Asset marked as ready_for_release",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "process_stage": asset.process_stage,
        },
    }, 200
# ------------------------
# Asset status (summary)
# ------------------------
@main.route("/assets/<int:asset_id>/status", methods=["GET"])
def get_asset_status(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    pre_arrival = (
        DepotPreArrival.query
        .filter_by(asset_id=asset.id)
        .order_by(DepotPreArrival.id.desc())
        .first()
    )

    compartments = []
    if asset.asset_type == "roadtanker":
        for c in sorted(asset.compartments, key=lambda x: x.number):
            cycles = [
                {
                    "cycle_number": wc.cycle_number,
                    "result": wc.result,
                    "started_at": wc.started_at,
                    "ended_at": wc.ended_at
                }
                for wc in c.wash_cycles
            ]

            compartments.append({
                "number": c.number,
                "last_cargo_material": c.last_cargo_material,
                "requested_to_wash": c.requested_to_wash,
                "wash_cycles": cycles
            })

    isotank_data = {}
    if asset.asset_type == "isotank":
        wash_cycles = [
            {
                "cycle_number": wc.cycle_number,
                "chemical_used": wc.chemical_used,
                "result": wc.result,
                "started_at": wc.started_at,
                "ended_at": wc.ended_at,
                "checked_by_name": wc.checked_by_name,
                "checked_by_role": wc.checked_by_role,
                "notes": wc.notes,
            }
            for wc in sorted(asset.isotank_wash_cycles, key=lambda x: x.cycle_number)
        ]

        repair_events = [
            {
                "id": r.id,
                "description": r.description,
                "result": r.result,
                "checked_by_name": r.checked_by_name,
                "price": r.price,
                "notes": r.notes,
            }
            for r in asset.repair_events
        ]

        transport_events = [
            {
                "id": t.id,
                "direction": t.direction,
                "transport_by": t.transport_by,
                "carrier_name": t.carrier_name,
                "origin": t.origin,
                "destination": t.destination,
                "transport_date": t.transport_date,
                "price": t.price,
            }
            for t in asset.transport_events
        ]

        release_doc = (
            ReleaseDocument.query
            .filter_by(asset_id=asset.id)
            .first()
        )

        isotank_data = {
            "wash_cycles": wash_cycles,
            "repair_events": repair_events,
            "transport_events": transport_events,
            "release_document": {
                "id": release_doc.id,
                "client_name": release_doc.client_name,
                "carrier_name": release_doc.carrier_name,
                "estimated_pickup_date": release_doc.estimated_pickup_date,
                "destination": release_doc.destination,
                "is_ready_for_pickup": release_doc.is_ready_for_pickup,
                "issued_at": release_doc.issued_at,
            } if release_doc else None,
        }

    return {
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "process_stage": asset.process_stage,
            "compartments_count": asset.compartments_count
        },
        "pre_arrival": {
            "id": pre_arrival.id if pre_arrival else None,
            "requested_service": pre_arrival.requested_service if pre_arrival else None,
            "declared_compartments_count": pre_arrival.declared_compartments_count if pre_arrival else None,
            "declared_wash_compartments": pre_arrival.declared_wash_compartments if pre_arrival else None
        },
        "compartments": compartments,
        "isotank_data": isotank_data if asset.asset_type == "isotank" else None,
    }, 200

# ------------------------
# Wash Certificates
# ------------------------
@main.route("/assets/<int:asset_id>/wash-certificate", methods=["POST"])
def issue_wash_certificate(asset_id):
    data = request.get_json() or {}
    wash_completed_at = data.get("wash_completed_at")
    if wash_completed_at:
        wash_completed_at = datetime.fromisoformat(wash_completed_at)

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type not in ("roadtanker", "isotank"):
        return {"error": "Wash certificate is only for roadtanker or isotank"}, 400

    if asset.status != "ready_for_release":
        return {
            "error": "Wash certificate can only be issued when asset.status == 'ready_for_release'",
            "current_status": asset.status
        }, 400

    existing = WashCertificate.query.filter_by(asset_id=asset.id).first()
    if existing:
        return {
            "error": "Wash certificate already exists for this asset",
            "certificate_id": existing.id
        }, 400

    # לאיזוטנק — בדיקה שיש מחזור שטיפה מאושר
    if asset.asset_type == "isotank":
        last_wash = (
            IsotankWashCycle.query
            .filter_by(asset_id=asset.id)
            .order_by(IsotankWashCycle.cycle_number.desc())
            .first()
        )
        if not last_wash or last_wash.result != "pass":
            return {
                "error": "Cannot issue certificate: no approved wash cycle found",
                "last_wash_result": last_wash.result if last_wash else None
            }, 400

        total_cycles = IsotankWashCycle.query.filter_by(asset_id=asset.id).count()
    else:
        total_cycles = None

    cert = WashCertificate(
        asset_id=asset.id,
        issued_by_name=data["issued_by_name"],
        issued_by_role=data["issued_by_role"],
        notes=data.get("notes"),
        client_name=data.get("client_name"),
        client_address=data.get("client_address"),
        last_cargo=data.get("last_cargo"),
        wash_completed_at=wash_completed_at,
        drying_performed=data.get("drying_performed"),
        cleaning_details=data.get("cleaning_details"),
        additional_services=data.get("additional_services"),
        total_wash_cycles=total_cycles,
        service_transportation=data.get("service_transportation"),
        service_polish=data.get("service_polish"),
        service_repair=data.get("service_repair"),
        service_photo_set=data.get("service_photo_set"),
        service_vacuum_test=data.get("service_vacuum_test"),
        service_storage=data.get("service_storage"),
        service_maintenance=data.get("service_maintenance"),
        service_test=data.get("service_test"),
    )
    db.session.add(cert)
    db.session.commit()

    return {
        "message": "Wash certificate issued",
        "certificate": {
            "id": cert.id,
            "asset_id": cert.asset_id,
            "asset_type": asset.asset_type,
            "issued_at": cert.issued_at,
            "issued_by_name": cert.issued_by_name,
            "issued_by_role": cert.issued_by_role,
            "client_name": cert.client_name,
            "client_address": cert.client_address,
            "last_cargo": cert.last_cargo,
            "wash_completed_at": cert.wash_completed_at,
            "drying_performed": cert.drying_performed,
            "cleaning_details": cert.cleaning_details,
            "additional_services": cert.additional_services,
            "total_wash_cycles": cert.total_wash_cycles,
            "service_transportation": cert.service_transportation,
            "service_polish": cert.service_polish,
            "service_repair": cert.service_repair,
            "service_photo_set": cert.service_photo_set,
            "service_vacuum_test": cert.service_vacuum_test,
            "service_storage": cert.service_storage,
            "service_maintenance": cert.service_maintenance,
            "service_test": cert.service_test,
            "status": cert.status,
        }
    }, 201

@main.route("/wash-certificates/<int:certificate_id>", methods=["GET"])
def get_wash_certificate(certificate_id):
    cert = WashCertificate.query.get(certificate_id)
    if not cert:
        return {"error": "Wash certificate not found"}, 404

    return {
        "certificate": {
            "id": cert.id,
            "asset_id": cert.asset_id,
            "asset_identifier": cert.asset.identifier if cert.asset else None,
            "issued_at": cert.issued_at,
            "issued_by_name": cert.issued_by_name,
            "issued_by_role": cert.issued_by_role,
            "notes": cert.notes,
            "status": cert.status
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/send-to-storage", methods=["PATCH"])
def isotank_send_to_storage(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "This endpoint is only for isotank assets"}, 400

    if asset.status != "arrived":
        return {
            "error": "Asset must have status 'arrived' to be sent to storage",
            "current_status": asset.status
        }, 400

    if asset.process_stage not in ("arrived", "washing", "in_repair", "transport"):
        return {
            "error": f"Cannot move to in_storage from current stage: {asset.process_stage}",
            "current_process_stage": asset.process_stage
        }, 400

    asset.process_stage = "in_storage"
    db.session.commit()

    return {
        "message": "Isotank moved to in_storage",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "status": asset.status,
            "process_stage": asset.process_stage,
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/send-to-washing", methods=["PATCH"])
def isotank_send_to_washing(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "This endpoint is only for isotank assets"}, 400

    if asset.status != "arrived":
        return {
            "error": "Asset must have status 'arrived' to be sent to washing",
            "current_status": asset.status
        }, 400

    if asset.process_stage not in ("arrived", "in_storage", "in_repair"):
        return {
            "error": f"Cannot move to washing from current stage: {asset.process_stage}",
            "current_process_stage": asset.process_stage
        }, 400

    asset.process_stage = "washing"
    db.session.commit()

    return {
        "message": "Isotank moved to washing",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "status": asset.status,
            "process_stage": asset.process_stage,
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/send-to-repair", methods=["PATCH"])
def isotank_send_to_repair(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "This endpoint is only for isotank assets"}, 400

    if asset.status != "arrived":
        return {
            "error": "Asset must have status 'arrived' to be sent to repair",
            "current_status": asset.status
        }, 400

    if asset.process_stage not in ("arrived", "in_storage", "washing"):
        return {
            "error": f"Cannot move to in_repair from current stage: {asset.process_stage}",
            "current_process_stage": asset.process_stage
        }, 400

    asset.process_stage = "in_repair"
    db.session.commit()

    return {
        "message": "Isotank moved to in_repair",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "status": asset.status,
            "process_stage": asset.process_stage,
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/transport-events", methods=["POST"])
def create_transport_event(asset_id):
    data = request.get_json() or {}

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "Transport events are only for isotank assets"}, 400

    # ולידציה של שדות חובה
    direction = data.get("direction")
    if direction not in ("inbound", "outbound"):
        return {"error": "direction must be 'inbound' or 'outbound'"}, 400

    transport_by = data.get("transport_by")
    if transport_by not in ("eco_depot", "external"):
        return {"error": "transport_by must be 'eco_depot' or 'external'"}, 400

    transport_date = data.get("transport_date")
    if not transport_date:
        return {"error": "transport_date is required"}, 400
    try:
        transport_date = datetime.fromisoformat(transport_date)
    except Exception:
        return {"error": "transport_date must be a valid ISO date (e.g. '2026-03-08T10:00:00')"}, 400

    # carrier_name חובה כש external
    carrier_name = data.get("carrier_name")
    if transport_by == "external" and not carrier_name:
        return {"error": "carrier_name is required when transport_by is 'external'"}, 400

    # price רלוונטי רק כש eco_depot
    price = data.get("price")
    if transport_by == "external" and price:
        return {"error": "price is not relevant when transport_by is 'external'"}, 400

    event = TransportEvent(
        asset_id=asset.id,
        direction=direction,
        transport_by=transport_by,
        carrier_name=carrier_name,
        origin=data.get("origin"),
        destination=data.get("destination"),
        transport_date=transport_date,
        price=price,
        notes=data.get("notes"),
    )
    db.session.add(event)
    db.session.commit()

    return {
        "message": "Transport event created",
        "transport_event": {
            "id": event.id,
            "asset_id": event.asset_id,
            "direction": event.direction,
            "transport_by": event.transport_by,
            "carrier_name": event.carrier_name,
            "origin": event.origin,
            "destination": event.destination,
            "transport_date": event.transport_date,
            "price": event.price,
            "notes": event.notes,
        }
    }, 201

@main.route("/isotanks/<int:asset_id>/wash-cycles", methods=["POST"])
def start_isotank_wash_cycle(asset_id):
    data = request.get_json() or {}

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "This endpoint is only for isotank assets"}, 400

    if asset.status != "arrived":
        return {
            "error": "Asset must have status 'arrived' to start a wash cycle",
            "current_status": asset.status
        }, 400

    if asset.process_stage != "washing":
        return {
            "error": "Asset must be in process_stage 'washing' to start a wash cycle",
            "current_process_stage": asset.process_stage
        }, 400

    last_cycle = (
        IsotankWashCycle.query
        .filter_by(asset_id=asset.id)
        .order_by(IsotankWashCycle.cycle_number.desc())
        .first()
    )
    next_num = 1 if not last_cycle else last_cycle.cycle_number + 1

    cycle = IsotankWashCycle(
        asset_id=asset.id,
        cycle_number=next_num,
        chemical_used=data.get("chemical_used"),
        notes=data.get("notes"),
    )
    db.session.add(cycle)
    db.session.commit()

    return {
        "message": "Isotank wash cycle started",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "status": asset.status,
            "process_stage": asset.process_stage,
        },
        "wash_cycle": {
            "id": cycle.id,
            "cycle_number": cycle.cycle_number,
            "chemical_used": cycle.chemical_used,
            "started_at": cycle.started_at,
            "notes": cycle.notes,
        }
    }, 201


@main.route("/isotank-wash-cycles/<int:cycle_id>/finish", methods=["PATCH"])
def finish_isotank_wash_cycle(cycle_id):
    data = request.get_json() or {}

    cycle = IsotankWashCycle.query.get(cycle_id)
    if not cycle:
        return {"error": "Isotank wash cycle not found"}, 404

    result = data.get("result")
    if result not in ("pass", "fail"):
        return {"error": "result must be 'pass' or 'fail'"}, 400

    cycle.result = result
    cycle.ended_at = datetime.utcnow()
    cycle.notes = data.get("notes", cycle.notes)
    cycle.checked_by_name = data.get("checked_by_name")
    cycle.checked_by_role = data.get("checked_by_role", cycle.checked_by_role)

    db.session.commit()

    return {
        "message": "Isotank wash cycle finished",
        "wash_cycle": {
            "id": cycle.id,
            "asset_id": cycle.asset_id,
            "cycle_number": cycle.cycle_number,
            "result": cycle.result,
            "started_at": cycle.started_at,
            "ended_at": cycle.ended_at,
            "checked_by_name": cycle.checked_by_name,
            "checked_by_role": cycle.checked_by_role,
            "notes": cycle.notes,
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/repair-events", methods=["POST"])
def create_repair_event(asset_id):
    data = request.get_json() or {}

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "Repair events are only for isotank assets"}, 400

    if asset.status != "arrived":
        return {
            "error": "Asset must have status 'arrived' to create a repair event",
            "current_status": asset.status
        }, 400

    if asset.process_stage != "in_repair":
        return {
            "error": "Asset must be in process_stage 'in_repair' to create a repair event",
            "current_process_stage": asset.process_stage
        }, 400

    result = data.get("result")
    if result not in ("pass", "fail"):
        return {"error": "result must be 'pass' or 'fail'"}, 400

    event = RepairEvent(
        asset_id=asset.id,
        description=data.get("description"),
        result=result,
        checked_by_name=data.get("checked_by_name"),
        checked_by_role=data.get("checked_by_role", "qc"),
        price=data.get("price"),
        notes=data.get("notes"),
    )
    db.session.add(event)
    db.session.commit()

    return {
        "message": "Repair event created",
        "repair_event": {
            "id": event.id,
            "asset_id": event.asset_id,
            "description": event.description,
            "result": event.result,
            "checked_by_name": event.checked_by_name,
            "checked_by_role": event.checked_by_role,
            "price": event.price,
            "notes": event.notes,
        }
    }, 201

@main.route("/isotanks/<int:asset_id>/mark-ready-for-release", methods=["PATCH"])
def isotank_mark_ready_for_release(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "This endpoint is only for isotank assets"}, 400

    if asset.status != "arrived":
        return {
            "error": "Asset must have status 'arrived'",
            "current_status": asset.status
        }, 400

    # בדיקת שטיפה — חובה
    last_wash = (
        IsotankWashCycle.query
        .filter_by(asset_id=asset.id)
        .order_by(IsotankWashCycle.cycle_number.desc())
        .first()
    )
    if not last_wash or last_wash.result != "pass":
        return {
            "error": "Asset cannot be marked ready: no approved wash cycle found",
            "last_wash_result": last_wash.result if last_wash else None
        }, 400

    # בדיקת תיקון — רק אם קיים
    last_repair = (
        RepairEvent.query
        .filter_by(asset_id=asset.id)
        .order_by(RepairEvent.id.desc())
        .first()
    )
    if last_repair and last_repair.result != "pass":
        return {
            "error": "Asset cannot be marked ready: last repair event is not approved",
            "last_repair_result": last_repair.result
        }, 400

    asset.status = "ready_for_release"
    asset.process_stage = "ready_for_release"
    db.session.commit()

    return {
        "message": "Isotank marked as ready for release",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "status": asset.status,
            "process_stage": asset.process_stage,
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/release-document", methods=["POST"])
def create_release_document(asset_id):
    data = request.get_json() or {}

    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.asset_type != "isotank":
        return {"error": "Release document is only for isotank assets"}, 400

    if asset.status != "ready_for_release":
        return {
            "error": "Release document can only be created when asset.status == 'ready_for_release'",
            "current_status": asset.status
        }, 400

    # ולידציה של שדות חובה
    client_name = data.get("client_name")
    if not client_name:
        return {"error": "client_name is required"}, 400

    issued_by_name = data.get("issued_by_name")
    if not issued_by_name:
        return {"error": "issued_by_name is required"}, 400

    issued_by_role = data.get("issued_by_role")
    if not issued_by_role:
        return {"error": "issued_by_role is required"}, 400

    carrier_type = data.get("carrier_type")
    if carrier_type and carrier_type not in ("eco_depot", "external"):
        return {"error": "carrier_type must be 'eco_depot' or 'external'"}, 400

    estimated_pickup_date = data.get("estimated_pickup_date")
    if estimated_pickup_date:
        try:
            estimated_pickup_date = datetime.fromisoformat(estimated_pickup_date)
        except Exception:
            return {"error": "estimated_pickup_date must be a valid ISO date"}, 400

    doc = ReleaseDocument(
        asset_id=asset.id,
        client_name=client_name,
        carrier_name=data.get("carrier_name"),
        carrier_type=carrier_type,
        estimated_pickup_date=estimated_pickup_date,
        destination=data.get("destination"),
        wash_approved=data.get("wash_approved"),
        drying_approved=data.get("drying_approved"),
        is_ready_for_pickup=data.get("is_ready_for_pickup", False),
        notes=data.get("notes"),
        issued_by_name=issued_by_name,
        issued_by_role=issued_by_role,
    )
    db.session.add(doc)
    db.session.commit()

    return {
        "message": "Release document created",
        "release_document": {
            "id": doc.id,
            "asset_id": doc.asset_id,
            "client_name": doc.client_name,
            "carrier_name": doc.carrier_name,
            "carrier_type": doc.carrier_type,
            "estimated_pickup_date": doc.estimated_pickup_date,
            "destination": doc.destination,
            "wash_approved": doc.wash_approved,
            "drying_approved": doc.drying_approved,
            "is_ready_for_pickup": doc.is_ready_for_pickup,
            "notes": doc.notes,
            "issued_at": doc.issued_at,
            "issued_by_name": doc.issued_by_name,
            "issued_by_role": doc.issued_by_role,
        }
    }, 201

@main.route("/assets/<int:asset_id>/release", methods=["PATCH"])
def release_asset(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset:
        return {"error": "Asset not found"}, 404

    if asset.status != "ready_for_release":
        return {
            "error": "Asset must have status 'ready_for_release' to be released",
            "current_status": asset.status
        }, 400

    # רואדטנקר — חייב תעודת שטיפה
    if asset.asset_type == "roadtanker":
        cert = WashCertificate.query.filter_by(asset_id=asset.id).first()
        if not cert:
            return {
                "error": "Cannot release roadtanker: no wash certificate found"
            }, 400

    # איזוטנק — חייב תעודת שחרור
    if asset.asset_type == "isotank":
        release_doc = ReleaseDocument.query.filter_by(asset_id=asset.id).first()
        if not release_doc:
            return {
                "error": "Cannot release isotank: no release document found"
            }, 400

    asset.status = "released"
    asset.process_stage = "released"
    db.session.commit()

    return {
        "message": "Asset released successfully",
        "asset": {
            "id": asset.id,
            "identifier": asset.identifier,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "process_stage": asset.process_stage,
        }
    }, 200

@main.route("/wash-certificates", methods=["GET"])
def list_wash_certificates():
    asset_type = request.args.get("asset_type")

    query = WashCertificate.query
    if asset_type:
        query = query.join(Asset).filter(Asset.asset_type == asset_type)

    certs = query.order_by(WashCertificate.id).all()

    return {
        "wash_certificates": [
            {
                "id": c.id,
                "asset_id": c.asset_id,
                "asset_identifier": c.asset.identifier if c.asset else None,
                "asset_type": c.asset.asset_type if c.asset else None,
                "issued_at": c.issued_at,
                "issued_by_name": c.issued_by_name,
                "client_name": c.client_name,
                "last_cargo": c.last_cargo,
                "status": c.status,
            }
            for c in certs
        ]
    }, 200

@main.route("/isotanks/<int:asset_id>/wash-cycles", methods=["GET"])
def list_isotank_wash_cycles(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset or asset.asset_type != "isotank":
        return {"error": "Isotank not found"}, 404

    cycles = sorted(asset.isotank_wash_cycles, key=lambda x: x.cycle_number)
    return {
        "asset_id": asset_id,
        "asset_identifier": asset.identifier,
        "wash_cycles": [
            {
                "id": wc.id,
                "cycle_number": wc.cycle_number,
                "chemical_used": wc.chemical_used,
                "result": wc.result,
                "started_at": wc.started_at,
                "ended_at": wc.ended_at,
                "checked_by_name": wc.checked_by_name,
                "checked_by_role": wc.checked_by_role,
                "notes": wc.notes,
            }
            for wc in cycles
        ]
    }, 200


@main.route("/isotanks/<int:asset_id>/repair-events", methods=["GET"])
def list_isotank_repair_events(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset or asset.asset_type != "isotank":
        return {"error": "Isotank not found"}, 404

    return {
        "asset_id": asset_id,
        "asset_identifier": asset.identifier,
        "repair_events": [
            {
                "id": r.id,
                "description": r.description,
                "result": r.result,
                "checked_by_name": r.checked_by_name,
                "checked_by_role": r.checked_by_role,
                "price": r.price,
                "notes": r.notes,
            }
            for r in asset.repair_events
        ]
    }, 200


@main.route("/isotanks/<int:asset_id>/transport-events", methods=["GET"])
def list_isotank_transport_events(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset or asset.asset_type != "isotank":
        return {"error": "Isotank not found"}, 404

    return {
        "asset_id": asset_id,
        "asset_identifier": asset.identifier,
        "transport_events": [
            {
                "id": t.id,
                "direction": t.direction,
                "transport_by": t.transport_by,
                "carrier_name": t.carrier_name,
                "origin": t.origin,
                "destination": t.destination,
                "transport_date": t.transport_date,
                "price": t.price,
                "notes": t.notes,
            }
            for t in asset.transport_events
        ]
    }, 200


@main.route("/isotanks/<int:asset_id>/release-document", methods=["GET"])
def get_isotank_release_document(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset or asset.asset_type != "isotank":
        return {"error": "Isotank not found"}, 404

    doc = ReleaseDocument.query.filter_by(asset_id=asset_id).first()
    if not doc:
        return {"error": "No release document found for this isotank"}, 404

    return {
        "asset_id": asset_id,
        "asset_identifier": asset.identifier,
        "release_document": {
            "id": doc.id,
            "client_name": doc.client_name,
            "carrier_name": doc.carrier_name,
            "carrier_type": doc.carrier_type,
            "estimated_pickup_date": doc.estimated_pickup_date,
            "destination": doc.destination,
            "wash_approved": doc.wash_approved,
            "drying_approved": doc.drying_approved,
            "is_ready_for_pickup": doc.is_ready_for_pickup,
            "notes": doc.notes,
            "issued_at": doc.issued_at,
            "issued_by_name": doc.issued_by_name,
            "issued_by_role": doc.issued_by_role,
        }
    }, 200

@main.route("/isotanks/<int:asset_id>/photos", methods=["POST"])
def add_photo_record(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset or asset.asset_type != "isotank":
        return {"error": "Isotank not found"}, 404

    data = request.get_json() or {}

    filename = data.get("filename")
    if not filename:
        return {"error": "filename is required"}, 400

    taken_by = data.get("taken_by")
    if not taken_by:
        return {"error": "taken_by is required"}, 400

    photo = PhotoRecord(
        asset_id=asset.id,
        filename=filename,
        taken_by=taken_by,
        stage=data.get("stage"),
        notes=data.get("notes"),
    )

    db.session.add(photo)
    db.session.commit()

    return {
        "message": "Photo record added",
        "photo": {
            "id": photo.id,
            "asset_id": photo.asset_id,
            "filename": photo.filename,
            "taken_at": photo.taken_at,
            "taken_by": photo.taken_by,
            "stage": photo.stage,
            "notes": photo.notes,
        }
    }, 201


@main.route("/isotanks/<int:asset_id>/photos", methods=["GET"])
def list_photo_records(asset_id):
    asset = Asset.query.get(asset_id)
    if not asset or asset.asset_type != "isotank":
        return {"error": "Isotank not found"}, 404

    photos = sorted(asset.photo_records, key=lambda x: x.taken_at)

    return {
        "asset_id": asset_id,
        "asset_identifier": asset.identifier,
        "photos": [
            {
                "id": p.id,
                "filename": p.filename,
                "taken_at": p.taken_at,
                "taken_by": p.taken_by,
                "stage": p.stage,
                "notes": p.notes,
            }
            for p in photos
        ]
    }, 200

@main.route("/clients/<int:client_id>/portal", methods=["GET"])
def client_portal(client_id):
    client = Client.query.get(client_id)
    if not client:
        return {"error": "Client not found"}, 404

    assets = Asset.query.filter(
        Asset.pre_arrivals.any(client_id=client_id)
    ).all()

    result = []
    for asset in assets:
        wash_cert = WashCertificate.query.filter_by(asset_id=asset.id).first()
        release_doc = ReleaseDocument.query.filter_by(asset_id=asset.id).first() if asset.asset_type == "isotank" else None
        photos = sorted(asset.photo_records, key=lambda x: x.taken_at) if asset.asset_type == "isotank" else []

        result.append({
            "asset_id": asset.id,
            "identifier": asset.identifier,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "process_stage": asset.process_stage,
            "wash_certificate": {
                "id": wash_cert.id,
                "issued_at": wash_cert.issued_at,
                "status": wash_cert.status,
            } if wash_cert else None,
            "release_document": {
                "id": release_doc.id,
                "destination": release_doc.destination,
                "estimated_pickup_date": release_doc.estimated_pickup_date,
                "is_ready_for_pickup": release_doc.is_ready_for_pickup,
            } if release_doc else None,
            "photos": [
                {
                    "id": p.id,
                    "filename": p.filename,
                    "stage": p.stage,
                    "taken_at": p.taken_at,
                }
                for p in photos
            ],
        })

    return {
        "client_id": client_id,
        "client_name": client.name,
        "assets": result,
    }, 200

def generate_disposal_certificate_pdf(event, cert):
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from bidi.algorithm import get_display

        pdfmetrics.registerFont(TTFont('Calibri', str(Path(__file__).parent / 'templates' / 'calibri.ttf')))
        pdfmetrics.registerFont(TTFont('CalibriBold', str(Path(__file__).parent / 'templates' / 'calibrib.ttf')))

        import re
        client_folder = event.client_name or event.billed_to
        client_folder = re.sub(r'[\\/:*?"<>|]', '_', client_folder)
        year = event.event_date.strftime("%Y")
        month = event.event_date.strftime("%m").lstrip("0")
        output_dir = Path(__file__).parents[2] / "output" / "לקוחות" / client_folder / "אישורים" / year / month
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"אישור_פריקה_{event.certificate_number}.pdf"
        output_path = output_dir / filename

        client = event.client_name or ''
        carrier = event.carrier_name or ''
        weight = str(event.weight_declared or '')
        packaging = f"{event.packaging_type or ''} {event.packaging_count or ''}".strip()
        notes = event.notes or ''
        event_date_str = event.event_date.strftime("%d/%m/%Y")

        STREAMS = {
            'emulsion': {
                'subject': 'הנדון : אישור קליטת שפכי אמולסיה.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון שפכי אמולסיה; {packaging}. {notes}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקני אקו אויל מקורם : {client}',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת שפכי אמולסיה, כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'base': {
                'subject': 'הנדון : אישור קליטת שפכי בסיס.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון שפכי בסיס; {packaging}. {notes}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד, ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת זרם בסיס, כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'acid': {
                'subject': 'הנדון : אישור קליטת שפכי חומצה.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון חומצה; {packaging}. {notes}',
                'item4': f'על פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד, ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת חומצה, כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'mineral_pit': {
                'subject': 'הנדון : אישור קליטת שפכי שמנים מינראליים.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון שפכי שמנים מינראליים. {notes}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקני אקו אויל מקורם בבור ההפרדה של חברת {client}.',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת {carrier} (המוביל) החומר הגיע מחברת {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת שפכי שמנים מינראליים כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'mineral_cube': {
                'subject': 'הנדון : אישור קליטת שפכי שמנים מינראליים.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון שפכי שמנים מינראליים, {packaging} {notes}.',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקני אקו אויל מקורם בחברת : {client}.',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת {carrier} (המוביל) החומר הגיע מחברת {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת שפכי שמנים מינראליים כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'mazut': {
                'subject': 'הנדון : אישור קליטת שפכי שמנים מינראליים.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון שפכי שמנים מינראליים, {packaging} {notes}.',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקני אקו אויל מקורם בחברת : {client}.',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת {carrier} (המוביל) החומר הגיע מחברת {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת שפכי שמנים מינראליים כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'washwater': {
                'subject': 'הנדון : אישור קליטת מי שטיפה.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון מי שטיפה. {packaging} {notes}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקני אקו אויל מקורם {client}.',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד; ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת {carrier} (המוביל) החומר הגיע {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת מי שטיפה כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'sanitary': {
                'subject': 'הנדון : אישור קליטת מי ביוב (מקלחות ושירותים מבניין פרטי או ציבורי בלבד).',
                'subject2': '(מי ביוב – חוק הרשויות המקומיות (ביוב) – תשכ"ב 1962).',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון מי ביוב. {packaging}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקננו מקורם בחברת : {client}',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת שפכי מי ביוב, כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'sanitary_eco': {
                'subject': 'הנדון : אישור קליטת מי ביוב (מקלחות ושירותים מבניין פרטי או ציבורי בלבד).',
                'subject2': '(מי ביוב – חוק הרשויות המקומיות (ביוב) – תשכ"ב 1962).',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון מי ביוב.',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקננו מקורם בחברת : {client}',
                    f'על פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת מי ביוב, כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'vegetable': {
                'subject': 'הנדון : אישור קליטת שפכי שומנים צמחיים.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון שפכי שומנים צמחיים. {notes}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו-אויל או אחריות של אקו-אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו-אויל לכך שהשפכים אשר נפרקו במתקננו מקורם בבור ההפרדה של : {client}.',
                    f'האחריות על השפכים, עד להגעתם למתקני אקו-אויל, הנה על : {client} בלבד, ואקו-אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על-פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}, ומקורו בבור מפריד השומנים.',
                    'על-פי הנחיית הרשויות, אישור זה אינו מהווה אישור קליטה קבוע לקליטת שפכי שומנים צמחיים, כי אם אישור חד-פעמי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו-אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
            'concentrate': {
                'subject': 'הנדון : אישור קליטת רכז שפכים.',
                'item1': f'הרינו לאשר כי קלטנו במתקן הטיפול שלנו : {weight} טון רכז שפכים. {packaging} {notes}',
                'legal': [
                    'אישור זה אינו מהווה אישור של אקו אויל או אחריות של אקו אויל למקור השפכים או אופיים.',
                    f'אישור זה אינו מהווה, בשום צורה שהיא, אישור של אקו אויל לכך שהשפכים אשר נפרקו במתקני אקו אויל מקורם : {client}',
                    f'האחריות על השפכים עד להגעתם למתקני אקו אויל הנה על {client} בלבד ואקו אויל אינה אחראית בשום צורה שהיא על אופן שאיבת השפכים, אופן הטענתם ואופן ההובלה של השפכים.',
                    f'על פי הצהרת : {carrier} (המוביל) החומר הגיע מחברת : {client}.',
                    'על פי הנחיית הרשויות אישור זה אינו מהווה אישור קליטה קבוע לקליטת רכז שפכים, כי אם אישור חד פעמי לפינוי.',
                    'אישור זה אינו ניתן להסבה.',
                    'אישור זה הינו אישור זמני עד פרעון התשלום עבור קליטת השפכים במתקן אקו אויל.',
                    'אי פרעון התשלום יגרור ביטול האישור לאלתר.',
                ],
            },
        }

        stream = STREAMS.get(event.material_classification)
        if not stream:
            return None, f"No template found for material: {event.material_classification}"

        c = canvas.Canvas(str(output_path), pagesize=A4)
        width, height = A4

        def rtl(text):
            return get_display(str(text), base_dir='R')

        def draw_rtl(canvas_obj, x, y, text, font='Calibri', size=11):
            canvas_obj.setFont(font, size)
            canvas_obj.drawRightString(x, y, rtl(text))

        def draw_rtl_wrapped(canvas_obj, x, y, text, font='Calibri', size=11, max_width=None):
            if max_width is None:
                max_width = width - 3*cm
            canvas_obj.setFont(font, size)
            words = text.split(' ')
            lines = []
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word])
                if canvas_obj.stringWidth(rtl(test_line), font, size) <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))
            for line in lines:
                canvas_obj.drawRightString(x, y, rtl(line))
                y -= 0.6*cm
            return y

        # לוגו ראשי - פינה ימין עליון
        logo_path = str(Path(__file__).parent / 'templates' / 'logo_eco-oil.png')
        c.drawImage(logo_path, width - 5*cm, height - 3.5*cm, width=4*cm, height=2.5*cm, preserveAspectRatio=True)

        # סוג חומר - פינה שמאל עליון
        c.setFont('Calibri', 11)
        c.drawString(1.5*cm, height - 2*cm, rtl(stream['subject'].replace('הנדון : אישור קליטת ', '').replace('.', '')))

        # תאריך
        draw_rtl(c, width - 1.5*cm, height - 4.5*cm, event_date_str)

        # לכבוד + פרטי לקוח
        draw_rtl(c, width - 1.5*cm, height - 5.5*cm, 'לכבוד')
        draw_rtl(c, width - 1.5*cm, height - 6.2*cm, client)
        draw_rtl(c, width - 1.5*cm, height - 6.9*cm, event.client_address or '')

        # הנדון
        y_subject = height - 8.2*cm
        draw_rtl(c, width - 1.5*cm, y_subject, stream['subject'], font='CalibriBold', size=12)
        if stream.get('subject2'):
            y_subject -= 0.7*cm
            draw_rtl(c, width - 1.5*cm, y_subject, stream['subject2'], font='CalibriBold', size=12)

        # סעיף 1
        y = y_subject - 1.3*cm
        y = draw_rtl_wrapped(c, width - 1.5*cm, y, f'.1    {stream["item1"]}')

        # סעיף 2
        y -= 0.2*cm
        draw_rtl(c, width - 1.5*cm, y, f'.2    החומר נפרק במפעלנו בתאריך : {event_date_str}')
        y -= 0.7*cm

        # סעיף 3
        draw_rtl(c, width - 1.5*cm, y, f'.3    החומר הועבר ע"י : {carrier} (להלן :"המוביל").')
        y -= 0.7*cm

        # סעיף 4 — רק לחומצה
        if stream.get('item4'):
            draw_rtl(c, width - 1.5*cm, y, f'.4    {stream["item4"]}')
            y -= 0.7*cm

        # פסקאות משפטיות
        y -= 0.3*cm
        for line in stream['legal']:
            y = draw_rtl_wrapped(c, width - 1.5*cm, y, line)

        # חתימה
        draw_rtl(c, width - 1.5*cm, y - 0.8*cm, 'בברכה')
        draw_rtl(c, width - 1.5*cm, y - 1.5*cm, 'חברת "אקו-אויל"')

        # קוד אישור
        exit_time = str(event.exit_time) if event.exit_time else ''
        verification_line = f'קוד אישור : {event_date_str}  {exit_time}    {cert.verification_code}'
        draw_rtl(c, width - 1.5*cm, 4.5*cm, verification_line)

        # העתק
        copy_lines = [
            'העתק : המשרד לאיכות הסביבה – מחוז חיפה',
            '           מכון טיהור שפכים חיפה',
            '           איגוד ערים חיפה',
        ]
        y_copy = 3.8*cm
        for line in copy_lines:
            draw_rtl(c, width - 1.5*cm, y_copy, line)
            y_copy -= 0.5*cm

        # פוטר
        footer_path = str(Path(__file__).parent / 'templates' / 'footer_logo.png')
        c.drawImage(footer_path, 1*cm, 0.5*cm, width=width - 2*cm, height=1.5*cm, preserveAspectRatio=True)

        c.save()
        return str(output_path), None

    except Exception as e:
        return None, str(e)

# ------------------------
# Eco-Oil / Disposal Events
# ------------------------
@main.route("/eco-oil/disposal-events", methods=["POST"])
def create_disposal_event():
    data = request.get_json() or {}

    # שדות חובה
    certificate_number = data.get("certificate_number")
    if not certificate_number:
        return {"error": "certificate_number is required"}, 400

    event_date = data.get("event_date")
    if not event_date:
        return {"error": "event_date is required"}, 400
    try:
        event_date = datetime.fromisoformat(event_date)
    except Exception:
        return {"error": "event_date must be a valid ISO date (e.g. '2026-03-11T08:00:00')"}, 400

    billed_to = data.get("billed_to")
    if not billed_to:
        return {"error": "billed_to is required"}, 400

    material_classification = data.get("material_classification")
    if not material_classification:
        return {"error": "material_classification is required"}, 400
    client_id = data.get("client_id")

    # בדיקת כפילות
    existing = DisposalEvent.query.filter_by(certificate_number=certificate_number).first()
    if existing:
        return {"error": f"certificate_number '{certificate_number}' already exists"}, 400

    event = DisposalEvent(
        certificate_number=certificate_number,
        random_code=data.get("random_code"),
        event_date=event_date,
        carrier_id=data.get("carrier_id"),
        carrier_name=data.get("carrier_name"),
        vehicle_number=data.get("vehicle_number"),
        client_name=data.get("client_name"),
        client_address=data.get("client_address"),
        billed_to=billed_to,
        material_classification=material_classification,
        client_id=client_id,
        is_hazardous=data.get("is_hazardous", False),
        weight_entry=data.get("weight_entry"),
        weight_declared=data.get("weight_declared"),
        packaging_type=data.get("packaging_type"),
        packaging_count=data.get("packaging_count"),
        notes=data.get("notes"),
    )
    db.session.add(event)
    db.session.commit()

    return {
        "message": "Disposal event created",
        "disposal_event": {
            "id": event.id,
            "certificate_number": event.certificate_number,
            "event_date": event.event_date,
            "client_name": event.client_name,
            "billed_to": event.billed_to,
            "material_classification": event.material_classification,
            "is_hazardous": event.is_hazardous,
            "weight_entry": event.weight_entry,
            "weight_declared": event.weight_declared,
        }
    }, 201


@main.route("/eco-oil/disposal-events/<int:event_id>/close", methods=["PATCH"])
def close_disposal_event(event_id):
    data = request.get_json() or {}

    event = DisposalEvent.query.get(event_id)
    if not event:
        return {"error": "Disposal event not found"}, 404

    # בדיקת כפילות — אם כבר קיים certificate לאירוע הזה
    existing_cert = DisposalCertificate.query.filter_by(disposal_event_id=event.id).first()
    if existing_cert:
        return {
            "error": "Disposal event is already closed",
            "certificate_id": existing_cert.id
        }, 400

    # weight_exit חובה
    weight_exit = data.get("weight_exit")
    if weight_exit is None:
        return {"error": "weight_exit is required"}, 400
    try:
        weight_exit = float(weight_exit)
    except Exception:
        return {"error": "weight_exit must be a number"}, 400

    # issued_by_name חובה (לצורך ה-certificate)
    issued_by_name = data.get("issued_by_name")
    if not issued_by_name:
        return {"error": "issued_by_name is required"}, 400

    # exit_time — אופציונלי, פורמט HH:MM
    exit_time_str = data.get("exit_time")
    if exit_time_str:
        try:
            exit_time = datetime.strptime(exit_time_str, "%H:%M").time()
        except Exception:
            return {"error": "exit_time must be in HH:MM format (e.g. '14:30')"}, 400
    else:
        exit_time = None

    # עדכון האירוע
    event.weight_exit = weight_exit
    event.exit_time = exit_time

    if event.weight_entry is not None:
        event.weight_net = event.weight_entry - weight_exit

    # בדיקת הצהרת יצרן תקפה — רק אם יש client_id על האירוע
    if event.client_id:
        valid_declaration = ProducerDeclaration.query.filter_by(
            client_id=event.client_id,
            material_classification=event.material_classification,
            is_active=True,
        ).filter(
            ProducerDeclaration.valid_from <= event.event_date,
            ProducerDeclaration.valid_until >= event.event_date,
        ).first()

        if not valid_declaration:
            return {
                "error": "Cannot issue certificate: no valid producer declaration found for this client and material",
                "client_id": event.client_id,
                "material_classification": event.material_classification,
                "event_date": str(event.event_date),
            }, 400

    # יצירת certificate אוטומטית
    verification_code = f"ECO-{event.event_date.strftime('%Y%m%d')}-{event.id:03d}-{secrets.token_hex(3).upper()}"
    cert = DisposalCertificate(
        disposal_event_id=event.id,
        issued_by_name=issued_by_name,
        sent_to_email=data.get("sent_to_email"),
        notes=data.get("notes"),
        verification_code=verification_code,
    )
    db.session.add(cert)
    db.session.commit()
    # יצירת PDF אוטומטית
    pdf_path, pdf_error = generate_disposal_certificate_pdf(event, cert)
    return {
        "message": "Disposal event closed and certificate issued",
        "disposal_event": {
            "id": event.id,
            "certificate_number": event.certificate_number,
            "weight_entry": event.weight_entry,
            "weight_exit": event.weight_exit,
            "weight_net": event.weight_net,
            "exit_time": exit_time_str if exit_time_str else None,
        },
        "disposal_certificate": {
            "id": cert.id,
            "disposal_event_id": cert.disposal_event_id,
            "issued_at": cert.issued_at,
            "issued_by_name": cert.issued_by_name,
            "sent_to_email": cert.sent_to_email,
            "verification_code": cert.verification_code,
            "pdf_saved_to": pdf_path,
            "pdf_error": pdf_error,
        }
    }, 201

@main.route("/eco-oil/disposal-events", methods=["GET"])
def list_disposal_events():
    material_classification = request.args.get("material_classification")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    status = request.args.get("status")  # open / closed

    query = DisposalEvent.query

    if material_classification:
        query = query.filter_by(material_classification=material_classification)

    if date_from:
        try:
            date_from = datetime.fromisoformat(date_from)
            query = query.filter(DisposalEvent.event_date >= date_from)
        except Exception:
            return {"error": "date_from must be a valid ISO date (e.g. '2026-03-01')"}, 400

    if date_to:
        try:
            date_to = datetime.fromisoformat(date_to)
            query = query.filter(DisposalEvent.event_date <= date_to)
        except Exception:
            return {"error": "date_to must be a valid ISO date (e.g. '2026-03-31')"}, 400

    if status == "open":
        query = query.filter(~DisposalEvent.disposal_certificate.any())
    elif status == "closed":
        query = query.filter(DisposalEvent.disposal_certificate.any())

    events = query.order_by(DisposalEvent.event_date.desc()).all()

    return {
        "total": len(events),
        "disposal_events": [
            {
                "id": e.id,
                "certificate_number": e.certificate_number,
                "event_date": e.event_date,
                "client_name": e.client_name,
                "billed_to": e.billed_to,
                "material_classification": e.material_classification,
                "is_hazardous": e.is_hazardous,
                "weight_entry": e.weight_entry,
                "weight_exit": e.weight_exit,
                "weight_net": e.weight_net,
                "status": "closed" if e.disposal_certificate else "open",
            }
            for e in events
        ]
    }, 200


@main.route("/eco-oil/disposal-events/<int:event_id>", methods=["GET"])
def get_disposal_event(event_id):
    event = DisposalEvent.query.get(event_id)
    if not event:
        return {"error": "Disposal event not found"}, 404

    cert = event.disposal_certificate[0] if event.disposal_certificate else None

    return {
        "disposal_event": {
            "id": event.id,
            "certificate_number": event.certificate_number,
            "random_code": event.random_code,
            "event_date": event.event_date,
            "exit_time": str(event.exit_time) if event.exit_time else None,
            "carrier_id": event.carrier_id,
            "carrier_name": event.carrier_name,
            "vehicle_number": event.vehicle_number,
            "client_name": event.client_name,
            "client_address": event.client_address,
            "billed_to": event.billed_to,
            "material_classification": event.material_classification,
            "is_hazardous": event.is_hazardous,
            "weight_entry": event.weight_entry,
            "weight_exit": event.weight_exit,
            "weight_net": event.weight_net,
            "weight_declared": event.weight_declared,
            "packaging_type": event.packaging_type,
            "packaging_count": event.packaging_count,
            "notes": event.notes,
            "status": "closed" if cert else "open",
        },
        "disposal_certificate": {
            "id": cert.id,
            "issued_at": cert.issued_at,
            "issued_by_name": cert.issued_by_name,
            "sent_at": cert.sent_at,
            "sent_to_email": cert.sent_to_email,
            "notes": cert.notes,
        } if cert else None,
    }, 200

# ------------------------
# Eco-Oil / Producer Declarations
# ------------------------
@main.route("/eco-oil/producer-declarations", methods=["POST"])
def create_producer_declaration():
    data = request.get_json() or {}

    client_id = data.get("client_id")
    if not client_id:
        return {"error": "client_id is required"}, 400

    client = Client.query.get(client_id)
    if not client:
        return {"error": "Client not found"}, 404

    material_name = data.get("material_name")
    if not material_name:
        return {"error": "material_name is required"}, 400

    material_classification = data.get("material_classification")
    if not material_classification:
        return {"error": "material_classification is required"}, 400

    valid_from = data.get("valid_from")
    if not valid_from:
        return {"error": "valid_from is required"}, 400
    try:
        valid_from = datetime.fromisoformat(valid_from)
    except Exception:
        return {"error": "valid_from must be a valid ISO date (e.g. '2026-01-01T00:00:00')"}, 400

    valid_until = data.get("valid_until")
    if not valid_until:
        return {"error": "valid_until is required"}, 400
    try:
        valid_until = datetime.fromisoformat(valid_until)
    except Exception:
        return {"error": "valid_until must be a valid ISO date (e.g. '2026-12-31T00:00:00')"}, 400

    declaration = ProducerDeclaration(
        client_id=client_id,
        material_name=material_name,
        material_classification=material_classification,
        valid_from=valid_from,
        valid_until=valid_until,
        annual_quantity_tons=data.get("annual_quantity_tons"),
        basel_code=data.get("basel_code"),
        notes=data.get("notes"),
        is_active=True,
    )
    db.session.add(declaration)
    db.session.commit()

    return {
        "message": "Producer declaration created",
        "producer_declaration": {
            "id": declaration.id,
            "client_id": declaration.client_id,
            "client_name": client.name,
            "material_name": declaration.material_name,
            "material_classification": declaration.material_classification,
            "valid_from": declaration.valid_from,
            "valid_until": declaration.valid_until,
            "annual_quantity_tons": declaration.annual_quantity_tons,
            "is_active": declaration.is_active,
        }
    }, 201