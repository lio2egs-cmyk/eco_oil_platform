"""
seed_demo_data.py
=================
סקריפט לטעינת נתוני דמו מאונונימיזים למסד הנתונים.
מריץ פעם אחת לפני הדגמה.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from datetime import datetime, timedelta
from app import create_app
from app.db import db, Client, Asset, ProducerDeclaration, AgreementDocument, DisposalEvent, DisposalCertificate, DepotPreArrival, Carrier

app = create_app()

# --- נתוני דמו מאונונימיזים ---

ECO_OIL_CLIENTS = [
    {"name": "תעשיות אלפא בע\"מ", "address": "א.ת. צפון, חיפה", "business_id": "500000001", "permit_number": "620001", "email": "alpha@demo.co.il"},
    {"name": "בטא מתכות בע\"מ", "address": "א.ת. תל-אביב", "business_id": "500000002", "permit_number": "620002", "email": "beta@demo.co.il"},
    {"name": "גמא כימיקלים בע\"מ", "address": "א.ת. בר-לב", "business_id": "500000003", "permit_number": "620003", "email": "gamma@demo.co.il"},
    {"name": "דלתא אנרגיה בע\"מ", "address": "א.ת. נשר", "business_id": "500000004", "permit_number": "620004", "email": "delta@demo.co.il"},
    {"name": "אפסילון תעשיות בע\"מ", "address": "א.ת. קריות", "business_id": "500000005", "permit_number": "620005", "email": "epsilon@demo.co.il"},
    {"name": "זטא עיבוד שבבי בע\"מ", "address": "א.ת. מגדל העמק", "business_id": "500000006", "permit_number": "620006", "email": "zeta@demo.co.il"},
    {"name": "אטא מכונות בע\"מ", "address": "א.ת. עכו", "business_id": "500000007", "permit_number": "620007", "email": "eta@demo.co.il"},
    {"name": "תטא פלסטיק בע\"מ", "address": "א.ת. כרמיאל", "business_id": "500000008", "permit_number": "620008", "email": "theta@demo.co.il"},
    {"name": "יוטא מפעלים בע\"מ", "address": "א.ת. יוקנעם", "business_id": "500000009", "permit_number": "620009", "email": "iota@demo.co.il"},
    {"name": "כאפא תעשיות בע\"מ", "address": "א.ת. נצרת עילית", "business_id": "500000010", "permit_number": "620010", "email": "kappa@demo.co.il"},
    {"name": "למבדה כימיה בע\"מ", "address": "א.ת. ראשון לציון", "business_id": "500000011", "permit_number": "620011", "email": "lambda@demo.co.il"},
    {"name": "מיו מתכות מתקדמות בע\"מ", "address": "א.ת. פתח תקווה", "business_id": "500000012", "permit_number": "620012", "email": "mu@demo.co.il"},
    {"name": "ניו אנרגיה בע\"מ", "address": "א.ת. אשדוד", "business_id": "500000013", "permit_number": "620013", "email": "nu@demo.co.il"},
    {"name": "קסי תעשיות בע\"מ", "address": "א.ת. באר שבע", "business_id": "500000014", "permit_number": "620014", "email": "xi@demo.co.il"},
    {"name": "אומיקרון מפעלים בע\"מ", "address": "א.ת. חדרה", "business_id": "500000015", "permit_number": "620015", "email": "omicron@demo.co.il"},
]

ECO_OIL_DECLARATIONS = [
    {"client_idx": 0, "material_name": "מינרלי - שמן מנוע משומש", "material_classification": "mineral", "size": "קטן",
     "stream_num": "160708*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "חדר נקי", "basel_r": "R12/R1", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "קוביות",
     "valid_until": datetime(2026, 6, 1), "ceo": "ישראל כהן"},
    {"client_idx": 1, "material_name": "אמולסיה - תחליב שמן-מים", "material_classification": "emulsion", "size": "גדול",
     "stream_num": "130105*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "עיבוד שבבי", "basel_r": "R1", "basel_d": "D9", "quantity": "מעל 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2027, 11, 1), "ceo": "דוד לוי"},
    {"client_idx": 2, "material_name": "בסיס - תמיסה בסיסית", "material_classification": "base", "size": "קטן",
     "stream_num": "060201*", "basel_y": "Y34 - תמיסות בסיסיות", "basel_h": "H8", "un_group": "8",
     "treatment": "נטרול", "basel_r": "R5", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "ביובית",
     "valid_until": datetime(2027, 3, 1), "ceo": "יוסי מזרחי"},
    {"client_idx": 3, "material_name": "חומצה - תמיסה חומצית", "material_classification": "acid", "size": "קטן",
     "stream_num": "060101*", "basel_y": "Y34 - תמיסות חומציות", "basel_h": "H8", "un_group": "8",
     "treatment": "נטרול", "basel_r": "R5", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "ביובית",
     "valid_until": datetime(2027, 3, 1), "ceo": "רחל אברהם"},
    {"client_idx": 4, "material_name": "מי שטיפה תעשייתיים", "material_classification": "washwater", "size": "קטן",
     "stream_num": "160708*", "basel_y": "Y9 - פסולת שמנים/מים", "basel_h": "H12", "un_group": "9",
     "treatment": "חדר נקי", "basel_r": "R12", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2027, 3, 1), "ceo": "משה פרץ"},
    {"client_idx": 5, "material_name": "אמולסיה - נוזל קירור", "material_classification": "emulsion", "size": "קטן",
     "stream_num": "130105*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "עיבוד שבבי", "basel_r": "R1", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2025, 6, 1), "ceo": "שרה גולן"},  # פג תוקף!
    {"client_idx": 6, "material_name": "בסיס - שפכים בסיסיים", "material_classification": "base", "size": "גדול",
     "stream_num": "060201*", "basel_y": "Y34 - תמיסות בסיסיות", "basel_h": "H8", "un_group": "8",
     "treatment": "נטרול", "basel_r": "R5", "basel_d": "D9", "quantity": "מעל 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2026, 10, 1), "ceo": "אורי שפירא"},
    {"client_idx": 7, "material_name": "אמולסיה - שמן הידראולי", "material_classification": "emulsion", "size": "קטן",
     "stream_num": "130105*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "עיבוד שבבי", "basel_r": "R1", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2025, 5, 1), "ceo": "נועה ברק"},  # פג תוקף!
    {"client_idx": 8, "material_name": "מינרלי - שמן הידראולי", "material_classification": "mineral", "size": "גדול",
     "stream_num": "130110*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "חדר נקי", "basel_r": "R12/R1", "basel_d": "D9", "quantity": "מעל 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2026, 4, 1), "ceo": "אמיר שלום"},  # עומד לפוג!
    {"client_idx": 9, "material_name": "אמולסיה - תחליב חיתוך", "material_classification": "emulsion", "size": "קטן",
     "stream_num": "120109*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "עיבוד שבבי", "basel_r": "R1", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2027, 8, 1), "ceo": "תמר כץ"},
    {"client_idx": 10, "material_name": "מזוט - שמן מזוט משומש", "material_classification": "gasoil", "size": "גדול",
     "stream_num": "160708*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "מחזור", "basel_r": "R1", "basel_d": "D9", "quantity": "מעל 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2026, 3, 25), "ceo": "גיל אדלר"},  # עומד לפוג תוך 7 ימים!
    {"client_idx": 11, "material_name": "חומצה - חומצה גופרתית", "material_classification": "acid", "size": "גדול",
     "stream_num": "060101*", "basel_y": "Y34 - תמיסות חומציות", "basel_h": "H8", "un_group": "8",
     "treatment": "נטרול", "basel_r": "R5", "basel_d": "D9", "quantity": "מעל 10 טון", "packaging": "ביובית",
     "valid_until": datetime(2027, 5, 1), "ceo": "רון פרידמן"},
    {"client_idx": 12, "material_name": "מי שטיפה - שפכים תעשייתיים", "material_classification": "washwater", "size": "קטן",
     "stream_num": "160708*", "basel_y": "Y9 - פסולת שמנים/מים", "basel_h": "H12", "un_group": "9",
     "treatment": "חדר נקי", "basel_r": "R12", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2026, 9, 1), "ceo": "לילה חסן"},
    {"client_idx": 13, "material_name": "בסיס - נוזל ניקוי", "material_classification": "base", "size": "קטן",
     "stream_num": "060201*", "basel_y": "Y34 - תמיסות בסיסיות", "basel_h": "H8", "un_group": "8",
     "treatment": "נטרול", "basel_r": "R5", "basel_d": "D9", "quantity": "עד 10 טון", "packaging": "ביובית",
     "valid_until": datetime(2027, 1, 1), "ceo": "עמי שחר"},
    {"client_idx": 14, "material_name": "מינרלי - שמן טרנספורמטור", "material_classification": "mineral", "size": "גדול",
     "stream_num": "130110*", "basel_y": "Y9 - פסולת שמנים/מים/פחמימנים", "basel_h": "H12", "un_group": "9",
     "treatment": "חדר נקי", "basel_r": "R12/R1", "basel_d": "D9", "quantity": "מעל 10 טון", "packaging": "מיכלית",
     "valid_until": datetime(2026, 4, 10), "ceo": "טל גרינברג"},  # עומד לפוג!
]

ECO_DEPOT_CLIENTS = [
    "מוביל-א שאיבות בע\"מ",
    "מוביל-ב הובלות בע\"מ",
    "מוביל-ג לוגיסטיקה בע\"מ",
    "תעשיות דמו א' בע\"מ",
    "תעשיות דמו ב' בע\"מ",
]

DEPOT_ASSETS_ROADTANKER = [
    "RT-DEMO-001", "RT-DEMO-002", "RT-DEMO-003",
    "RT-DEMO-004", "RT-DEMO-005", "RT-DEMO-006",
    "RT-DEMO-007", "RT-DEMO-008",
]

DEPOT_ASSETS_ISOTANK = [
    "ISO-DEMO-001", "ISO-DEMO-002", "ISO-DEMO-003",
    "ISO-DEMO-004", "ISO-DEMO-005", "ISO-DEMO-006",
]

CARRIERS = [
    {"name": "הובלות צפון בע\"מ", "business_id": "510000001", "hazmat_license_number": "HZ-001"},
    {"name": "שאיבות מרכז בע\"מ", "business_id": "510000002", "hazmat_license_number": "HZ-002"},
    {"name": "לוגיסטיקה דרום בע\"מ", "business_id": "510000003", "hazmat_license_number": "HZ-003"},
]


def seed():
    with app.app_context():
        print("מתחיל טעינת נתוני דמו...")

        # --- מובילים ---
        print("יוצר מובילים...")
        carrier_objects = []
        for c in CARRIERS:
            carrier = Carrier(
                name=c["name"],
                business_id=c["business_id"],
                hazmat_license_number=c["hazmat_license_number"],
                hazmat_license_expiry=datetime(2027, 12, 31),
            )
            db.session.add(carrier)
            carrier_objects.append(carrier)
        db.session.commit()
        print(f"  נוצרו {len(carrier_objects)} מובילים")

        # --- לקוחות אקו אויל ---
        print("יוצר לקוחות אקו אויל...")
        oil_client_objects = []
        for c in ECO_OIL_CLIENTS:
            client = Client(
                name=c["name"],
                division="eco_oil",
                client_type="direct"
            )
            db.session.add(client)
            oil_client_objects.append((client, c))
        db.session.commit()
        print(f"  נוצרו {len(oil_client_objects)} לקוחות")

        # --- הצהרות יצרן ---
        print("יוצר הצהרות יצרן...")
        declaration_objects = []
        for decl_data in ECO_OIL_DECLARATIONS:
            client_obj, client_info = oil_client_objects[decl_data["client_idx"]]
            decl = ProducerDeclaration(
                client_id=client_obj.id,
                client_address=client_info["address"],
                business_id=client_info["business_id"],
                permit_number=client_info["permit_number"],
                ceo_name=decl_data["ceo"],
                client_email=client_info["email"],
                addressed_to=decl_data["ceo"],
                producer_size=decl_data["size"],
                material_name=decl_data["material_name"],
                material_classification=decl_data["material_classification"],
                waste_stream_number=decl_data["stream_num"],
                basel_y_code=decl_data["basel_y"],
                basel_h_code=decl_data["basel_h"],
                un_risk_group=str(decl_data["un_group"]),
                treatment_facility_type=decl_data["treatment"],
                basel_r_code=decl_data["basel_r"],
                basel_d_code=decl_data["basel_d"],
                annual_quantity_text=decl_data["quantity"],
                packaging_type=decl_data["packaging"],
                valid_from=datetime(2024, 1, 1),
                valid_until=decl_data["valid_until"],
                is_active=True,
                issued_at=datetime(2024, 1, 15),
            )
            db.session.add(decl)
            declaration_objects.append(decl)
        db.session.commit()
        print(f"  נוצרו {len(declaration_objects)} הצהרות")

        # --- הסכמים ---
        print("יוצר הסכמים...")
        for decl in declaration_objects:
            ag = AgreementDocument(
                declaration_id=decl.id,
                issued_by_name="יואב טואג",
                valid_from=decl.valid_from,
                valid_until=decl.valid_until,
                issued_at=datetime(2024, 1, 20),
            )
            db.session.add(ag)
        db.session.commit()
        print(f"  נוצרו {len(declaration_objects)} הסכמים")

        # --- אירועי פריקה ---
        print("יוצר אירועי פריקה...")
        classifications = ["mineral", "emulsion", "acid", "base", "washwater", "gasoil"]
        for i in range(15):
            client_obj, _ = oil_client_objects[i % len(oil_client_objects)]
            carrier = carrier_objects[i % len(carrier_objects)]
            event_date = datetime(2026, 1, 1) + timedelta(days=i * 7)
            event = DisposalEvent(
                certificate_number=f"ECO-2026-DEMO-{i+1:03d}",
                event_date=event_date,
                carrier_id=carrier.id,
                carrier_name=carrier.name,
                vehicle_number=f"12-345-{i+1:02d}",
                client_name=oil_client_objects[i % len(oil_client_objects)][0].name,
                client_address=oil_client_objects[i % len(oil_client_objects)][1]["address"],
                billed_to=oil_client_objects[i % len(oil_client_objects)][0].name,
                material_classification=classifications[i % len(classifications)],
                is_hazardous=True,
                weight_entry=round(15000 + i * 500, 1),
                weight_exit=round(5000 + i * 100, 1),
                weight_net=round(10000 + i * 400, 1),
                client_id=client_obj.id,
            )
            db.session.add(event)
        db.session.commit()
        print("  נוצרו 15 אירועי פריקה")

        # --- לקוחות אקו דיפו ---
        print("יוצר לקוחות אקו דיפו...")
        depot_client_objects = []
        for name in ECO_DEPOT_CLIENTS:
            client = Client(
                name=name,
                division="eco_depot",
                client_type="direct"
            )
            db.session.add(client)
            depot_client_objects.append(client)
        db.session.commit()
        print(f"  נוצרו {len(depot_client_objects)} לקוחות דיפו")

        # --- נכסים אקו דיפו ---
        print("יוצר נכסים...")
        asset_objects = []
        for identifier in DEPOT_ASSETS_ROADTANKER:
            asset = Asset(
                identifier=identifier,
                division="eco_depot",
                asset_type="roadtanker",
                status="confirmed",
                process_stage="washing",
                compartments_count=3,
            )
            db.session.add(asset)
            asset_objects.append(asset)

        for identifier in DEPOT_ASSETS_ISOTANK:
            asset = Asset(
                identifier=identifier,
                division="eco_depot",
                asset_type="isotank",
                status="confirmed",
                process_stage="washing",
            )
            db.session.add(asset)
            asset_objects.append(asset)
        db.session.commit()
        print(f"  נוצרו {len(asset_objects)} נכסים")

        # --- PreArrivals ---
        print("יוצר PreArrivals...")
        chemicals = ["חומצה גופרתית", "שמן מנוע", "תחליב קירור", "נוזל הידראולי", "בסיס NaOH"]
        for i, asset in enumerate(asset_objects[:10]):
            client = depot_client_objects[i % len(depot_client_objects)]
            pa = DepotPreArrival(
                asset_id=asset.id,
                client_id=client.id,
                msds_chemical_name=chemicals[i % len(chemicals)],
                requested_service="שטיפה + בדיקת לחץ",
                status="arrived",
                declared_compartments_count=3 if asset.asset_type == "roadtanker" else None,
            )
            db.session.add(pa)
        db.session.commit()
        print("  נוצרו 10 PreArrivals")

        print("\n✅ נתוני דמו נטענו בהצלחה!")
        print(f"  לקוחות אקו אויל: {len(oil_client_objects)}")
        print(f"  הצהרות יצרן: {len(declaration_objects)}")
        print(f"  הסכמים: {len(declaration_objects)}")
        print(f"  אירועי פריקה: 15")
        print(f"  לקוחות אקו דיפו: {len(depot_client_objects)}")
        print(f"  נכסים: {len(asset_objects)}")
        print(f"  PreArrivals: 10")
        print("\n  שימי לב: 3 הצהרות פגו תוקף, 2 עומדות לפוג ב-30 יום הקרובים")


if __name__ == "__main__":
    seed()
