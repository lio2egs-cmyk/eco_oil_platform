from flask import Blueprint, request
from .db import db, Client, DepotPreArrival, Asset, Compartment, WashCycle

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
    )

    db.session.add(asset)
    db.session.commit()

    return {"message": "Asset created successfully", "asset_id": asset.id}, 201


@main.route("/assets", methods=["GET"])
def list_assets():
    assets = Asset.query.order_by(Asset.id).all()
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
    asset.process_stage = "waiting"
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

    # fetch latest pre-arrival for this asset
    latest_pre = (
        DepotPreArrival.query
        .filter_by(asset_id=asset.id)
        .order_by(DepotPreArrival.id.desc())
        .first()
    )

    declared = (latest_pre.declared_wash_compartments if latest_pre else None)
    declared = (declared or "").strip()

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
        "compartments": compartments
    }, 200