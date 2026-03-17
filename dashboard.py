import streamlit as st
import json
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="אקו-סיסטם | לוח בקרה",
    page_icon="🌿",
    layout="wide"
)

# כותרת ראשית
st.title("🌿 אקו-סיסטם — מערכת ניהול חכמה")
st.markdown('**אקו-אויל ווירומטל בע"מ** | ניהול תפעולי ורגולציה חכמה')

st.divider()

# תפריט ניווט
tab1, tab2, tab3 = st.tabs(["📊 ניתוח AI", "🏭 אקו דיפו", "⚗️ אקו אויל"])

# ===== טאב 1: ניתוח AI =====
with tab1:
    st.header("ניתוח נתונים — מערכת סוכני AI")
    
    results_path = Path('data/analysis_results.json')
    if not results_path.exists():
        st.warning("טרם הורץ ניתוח. הריצי את crew_analysis.py קודם.")
    else:
        with open(results_path, encoding='utf-8') as f:
            results = json.load(f)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📋 Crew 1 — Data Analyst")
            with st.expander("איכות הנתונים", expanded=False):
                st.markdown(results.get('data_quality', ''))
            with st.expander("ניתוח עונתי", expanded=False):
                st.markdown(results.get('seasonal_analysis', ''))
            with st.expander("דוח EDA מלא", expanded=True):
                st.markdown(results.get('eda_report', ''))
        
        with col2:
            st.subheader("🔬 Crew 2 — Data Scientist")
            with st.expander("חומרים בעייתיים", expanded=False):
                st.markdown(results.get('problematic_materials', ''))
            with st.expander("ניתוח עלויות", expanded=False):
                st.markdown(results.get('cost_analysis', ''))
            with st.expander("המלצות ניהוליות", expanded=True):
                st.markdown(results.get('recommendations', ''))

# ===== טאב 2: אקו דיפו =====
with tab2:
    st.header("אקו דיפו — ניהול מיכלים")
    
    isotank_path = Path('data/isotank_2025.csv')
    if isotank_path.exists():
        df = pd.read_csv(isotank_path)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("סה״כ איזוטנקים 2025", len(df))
        with col2:
            st.metric("חודשים מתועדים", df['month'].nunique())
        with col3:
            top_material = df['last_material'].value_counts().index[0] if 'last_material' in df.columns else "—"
            st.metric("חומר נפוץ ביותר", str(top_material)[:20])
        
        st.subheader("כמות איזוטנקים לפי חודש")
        monthly = df.groupby('month').size().reset_index(name='כמות')
        month_order = ['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר']
        monthly['month'] = pd.Categorical(monthly['month'], categories=month_order, ordered=True)
        monthly = monthly.sort_values('month')
        st.bar_chart(monthly.set_index('month')['כמות'])
        
        st.subheader("נתונים גולמיים")
        st.dataframe(df.head(50), use_container_width=True)
        st.divider()

    # --- בדיקת סטטוס נכס ---
    st.subheader("🔍 בדיקת סטטוס נכס")
    asset_id_input = st.text_input("הכניסי מספר מזהה של נכס (לדוגמה: ABC-1234)")
    if st.button("בדוק סטטוס"):
        import requests
        res = requests.get("http://127.0.0.1:5000/assets")
        if res.status_code == 200:
            assets = res.json().get("assets", [])
            found = [a for a in assets if a["identifier"].upper() == asset_id_input.upper()]
            if found:
                asset = found[0]
                st.success(f"✅ נמצא: {asset['identifier']}")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("סוג נכס", asset["asset_type"])
                with col2:
                    st.metric("סטטוס", asset["status"])
                with col3:
                    st.metric("שלב תהליך", asset["process_stage"])
                status_res = requests.get(f"http://127.0.0.1:5000/assets/{asset['id']}/status")
                if status_res.status_code == 200:
                    status_data = status_res.json()
                    st.subheader("פירוט מצב הנכס")
                    st.json(status_data)
            else:
                st.warning(f"נכס עם מספר '{asset_id_input}' לא נמצא במערכת.")

    st.divider()

    # --- יצירת PreArrival ---
    st.subheader("📥 יצירת בקשת PreArrival חדשה")
    with st.form("pre_arrival_form"):
        col1, col2 = st.columns(2)
        with col1:
            pa_client_name = st.text_input("שם הלקוח")
            pa_asset_id = st.text_input("מספר מזהה של נכס")
            pa_asset_type = st.selectbox("סוג נכס", ["roadtanker", "isotank"])
        with col2:
            pa_chemical = st.text_input("שם החומר האחרון (MSDS)")
            pa_service = st.text_input("שירות מבוקש")
            pa_compartments = st.number_input("מספר תאים", min_value=0, max_value=6, value=0)
        pa_submitted = st.form_submit_button("צור PreArrival")

    if pa_submitted:
        import requests
        # יצירת לקוח
        client_res = requests.post("http://127.0.0.1:5000/clients", json={
            "name": pa_client_name,
            "division": "eco_depot",
            "client_type": "direct"
        })
        if client_res.status_code == 201:
            client_id = client_res.json()["client_id"]
            # יצירת נכס
            asset_res = requests.post("http://127.0.0.1:5000/assets", json={
                "identifier": pa_asset_id,
                "division": "eco_depot",
                "asset_type": pa_asset_type
            })
            if asset_res.status_code == 201:
                asset_db_id = asset_res.json()["asset_id"]
                # יצירת PreArrival
                pa_res = requests.post("http://127.0.0.1:5000/depot/pre-arrivals", json={
                    "asset_id": asset_db_id,
                    "client_id": client_id,
                    "msds_chemical_name": pa_chemical,
                    "requested_service": pa_service,
                    "declared_compartments_count": pa_compartments if pa_compartments > 0 else None,
                })
                if pa_res.status_code == 201:
                    st.success(f"✅ PreArrival נוצר בהצלחה!")
                else:
                    st.error("שגיאה ביצירת PreArrival")
            else:
                st.error("שגיאה ביצירת נכס — ייתכן שהמספר כבר קיים במערכת")
        else:
            st.error("שגיאה ביצירת לקוח")

# ===== טאב 3: אקו אויל =====
with tab3:
    st.header("אקו אויל — אירועי פריקה")
    st.info("המודול פעיל דרך ה-API. לצפייה בנתונים התחברי לשרת Flask.")
    
    st.subheader("זרמי חומרים נתמכים")
    streams = {
        "אמולסיה": "emulsion",
        "בסיס": "base", 
        "חומצה": "acid",
        "מינרלי (בור מפריד)": "mineral_pit",
        "מינרלי (קוביה)": "mineral_cube",
        "מזוט": "mazut",
        "מי שטיפה": "washwater",
        "סניטרי": "sanitary",
        "סניטרי שלוח": "sanitary_eco",
        "צמחי": "vegetable",
        "רכז שפכים": "concentrate"
    }
    
    cols = st.columns(3)
    for i, (name, key) in enumerate(streams.items()):
        with cols[i % 3]:
            st.success(f"✅ {name}")

    st.divider()

    # --- יצירת הצהרת יצרן ---
    st.subheader("📋 יצירת הצהרת יצרן חדשה")
    with st.form("declaration_form"):
        col1, col2 = st.columns(2)
        with col1:
            client_name = st.text_input("שם הלקוח")
            material_name = st.text_input("שם החומר")
            material_classification = st.selectbox("סיווג חומר", ["mineral", "emulsion", "acid", "base", "washwater", "gasoil"])
            producer_size = st.selectbox("גודל יצרן", ["קטן", "גדול"])
        with col2:
            business_id = st.text_input("מספר ח.פ.")
            permit_number = st.text_input("מספר היתר רעלים")
            client_address = st.text_input("כתובת")
            client_email = st.text_input("מייל לקוח")
        col3, col4 = st.columns(2)
        with col3:
            valid_from = st.date_input("תוקף מ-")
        with col4:
            valid_until = st.date_input("תוקף עד")
        submitted = st.form_submit_button("צור הצהרת יצרן")

    if submitted:
        import requests
        # קודם צור לקוח
        client_res = requests.post("http://127.0.0.1:5000/clients", json={
            "name": client_name,
            "division": "eco_oil",
            "client_type": "direct"
        })
        if client_res.status_code == 201:
            client_id = client_res.json()["client_id"]
            decl_res = requests.post("http://127.0.0.1:5000/eco-oil/producer-declarations", json={
                "client_id": client_id,
                "material_name": material_name,
                "material_classification": material_classification,
                "producer_size": producer_size,
                "business_id": business_id,
                "permit_number": permit_number,
                "client_address": client_address,
                "client_email": client_email,
                "valid_from": f"{valid_from}T00:00:00",
                "valid_until": f"{valid_until}T00:00:00",
            })
            if decl_res.status_code == 201:
                st.success("✅ הצהרת יצרן נוצרה בהצלחה!")
            else:
                st.error("שגיאה ביצירת הצהרה")
        else:
            st.error("שגיאה ביצירת לקוח")

    st.divider()

    # --- צפייה בהסכמים ---
    st.subheader("📄 הסכמים קיימים")
    import requests
    ag_res = requests.get("http://127.0.0.1:5000/eco-oil/agreements")
    if ag_res.status_code == 200:
        agreements = ag_res.json().get("agreements", [])
        if agreements:
            for ag in agreements:
                with st.expander(f"הסכם #{ag['id']} — {ag['material_name']} | {ag['client_name']}"):
                    st.write(f"**הונפק על ידי:** {ag['issued_by_name']}")
                    st.write(f"**תוקף:** {ag['valid_from'][:10]} עד {ag['valid_until'][:10]}")
                    if st.button(f"הורד PDF — הסכם {ag['id']}", key=f"pdf_{ag['id']}"):
                        pdf_res = requests.get(f"http://127.0.0.1:5000/eco-oil/agreements/{ag['id']}/pdf")
                        if pdf_res.status_code == 200:
                            st.download_button(
                                label="לחץ להורדה",
                                data=pdf_res.content,
                                file_name=f"הסכם_{ag['id']}.pdf",
                                mime="application/pdf",
                                key=f"dl_{ag['id']}"
                            )
        else:
            st.info("אין הסכמים במערכת עדיין.")
    else:
        st.warning("לא ניתן להתחבר לשרת Flask.")