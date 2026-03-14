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