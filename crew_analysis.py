import os
from dotenv import load_dotenv
load_dotenv()
import pandas as pd
import json
from anthropic import Anthropic
from pathlib import Path

client = Anthropic()

# ===== טעינת נתונים =====
def load_data():
    isotank = pd.read_csv('data/isotank_2025.csv')
    roadtanker = pd.read_csv('data/roadtanker_2025.csv')
    return isotank, roadtanker

# ===== סוכן בסיסי =====
def run_agent(role, goal, task, context=""):
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        system=f"אתה {role}. המטרה שלך: {goal}. ענה בעברית.",
        messages=[{"role": "user", "content": f"{task}\n\nנתונים:\n{context}"}]
    )
    return response.content[0].text

# ===== CREW 1: Data Analyst =====
def run_data_analyst_crew(isotank_df, roadtanker_df):
    print("\n🔍 Crew 1 — Data Analyst מתחיל...\n")

    # סוכן 1 — ניקוי ואימות
    isotank_summary = isotank_df.describe().to_string()
    roadtanker_summary = roadtanker_df.describe().to_string()
    
    agent1_output = run_agent(
        role="מומחה ניקוי נתונים",
        goal="לאמת ולנקות נתוני תפעול של מתקן טיפול שפכים תעשייתי",
        task="בדוק את איכות הנתונים: כמה שורות, כמה ערכים חסרים, האם הנתונים הגיוניים?",
        context=f"איזוטנק:\n{isotank_summary}\n\nרואדטנקר:\n{roadtanker_summary}"
    )
    print("✅ סוכן 1 — ניקוי נתונים הושלם")

    # סוכן 2 — ניתוח עונתי
    monthly = isotank_df.groupby('month').size().to_string()
    
    agent2_output = run_agent(
        role="אנליסט עסקי",
        goal="לזהות דפוסים עונתיים ועומסי עבודה במתקן",
        task="נתח את כמות האיזוטנקים לפי חודש. מהם החודשים העמוסים ביותר? מה ההשלכות התפעוליות?",
        context=f"כמות איזוטנקים לפי חודש:\n{monthly}"
    )
    print("✅ סוכן 2 — ניתוח עונתי הושלם")

    # סוכן 3 — דוח EDA
    agent3_output = run_agent(
        role="כותב דוחות עסקיים",
        goal="לפיק דוח תובנות ברור להנהלה",
        task="כתוב דוח תובנות קצר (5-7 נקודות) להנהלת אקו דיפו על בסיס הממצאים הבאים:",
        context=f"ממצאי ניקוי נתונים:\n{agent1_output}\n\nממצאי ניתוח עונתי:\n{agent2_output}"
    )
    print("✅ סוכן 3 — דוח EDA הושלם")

    return {
        "data_quality": agent1_output,
        "seasonal_analysis": agent2_output,
        "eda_report": agent3_output
    }

# ===== CREW 2: Data Scientist =====
def run_data_scientist_crew(isotank_df, crew1_results):
    print("\n🔬 Crew 2 — Data Scientist מתחיל...\n")

    # סוכן 1 — זיהוי חומרים בעייתיים
    materials = isotank_df['last_material'].value_counts().head(20).to_string()
    
    agent1_output = run_agent(
        role="מומחה לחומרים כימיים תעשייתיים",
        goal="לזהות חומרים שגורמים לעלויות גבוהות או זמני טיפול ארוכים",
        task="נתח אילו חומרים מופיעים הכי הרבה. אילו מהם ידועים כבעייתיים לניקוי? מה ההמלצות לתמחור?",
        context=f"חומרים נפוצים באיזוטנקים:\n{materials}"
    )
    print("✅ סוכן 1 — זיהוי חומרים בעייתיים הושלם")

    # סוכן 2 — ניתוח עלויות
    cost_data = isotank_df[['last_material', 'total_cost', 'storage_days']].dropna().head(50).to_string()
    
    agent2_output = run_agent(
        role="אנליסט פיננסי",
        goal="לזהות פערים בתמחור ולהמליץ על תעריפים",
        task="נתח את העלויות לפי חומר וימי אחסנה. היכן יש פערים בין עלות גבוהה לתמחור נמוך?",
        context=f"נתוני עלויות:\n{cost_data}"
    )
    print("✅ סוכן 2 — ניתוח עלויות הושלם")

    # סוכן 3 — דוח המלצות
    agent3_output = run_agent(
        role="יועץ עסקי בכיר",
        goal="לפיק המלצות ניהוליות מעשיות",
        task="על בסיס הממצאים, כתוב 5 המלצות מעשיות להנהלת אקו דיפו לשיפור הרווחיות והיעילות:",
        context=f"ממצאי חומרים בעייתיים:\n{agent1_output}\n\nממצאי עלויות:\n{agent2_output}\n\nדוח EDA:\n{crew1_results['eda_report']}"
    )
    print("✅ סוכן 3 — דוח המלצות הושלם")

    return {
        "problematic_materials": agent1_output,
        "cost_analysis": agent2_output,
        "recommendations": agent3_output
    }

# ===== FLOW ראשי =====
def main():
    print("🚀 מערכת ניתוח אקו דיפו — מתחילה\n")
    
    isotank_df, roadtanker_df = load_data()
    print(f"נטענו {len(isotank_df)} רשומות איזוטנק ו-{len(roadtanker_df)} רשומות רואדטנקר")

    # Crew 1
    crew1_results = run_data_analyst_crew(isotank_df, roadtanker_df)
    
    # Crew 2
    crew2_results = run_data_scientist_crew(isotank_df, crew1_results)

    # שמירת תוצאות
    output = {**crew1_results, **crew2_results}
    Path('data').mkdir(exist_ok=True)
    with open('data/analysis_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n✅ הניתוח הושלם! התוצאות נשמרו ב-data/analysis_results.json")
    print("\n" + "="*50)
    print("📊 דוח EDA:")
    print(crew1_results['eda_report'])
    print("\n" + "="*50)
    print("💡 המלצות:")
    print(crew2_results['recommendations'])

if __name__ == "__main__":
    main()