# 🌿 Eco-Oil Smart Operations & Compliance Platform

> **Final Project — AI Development & Collaboration Course**  
> Industry-Simulated AI Product Workflow using Flask, CrewAI, Streamlit & Claude API

[![Python](https://img.shields.io/badge/Python-3.14-blue)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-green)](https://flask.palletsprojects.com)
[![Claude API](https://img.shields.io/badge/Claude-API-orange)](https://anthropic.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-red)](https://streamlit.io)
[![GitHub](https://img.shields.io/badge/GitHub-eco__oil__platform-black)](https://github.com/lio2egs-cmyk/eco_oil_platform)

---

## 📋 Project Overview

This platform is a real-world AI-powered operations management system built for **Eco-Oil Arrow Virometel Ltd.** — an industrial hazardous waste treatment facility in Haifa, Israel.

The system replaces manual, Excel-based workflows with a fully digital platform that includes:

- **Full lifecycle management** of industrial waste containers
- **Regulatory compliance automation** for hazardous materials (under Israeli environmental law)
- **AI-powered agents** for email processing, computer vision, and automated document delivery
- **Operational intelligence layer** using CrewAI multi-agent framework

---

## 🏢 Business Background

Eco-Oil Arrow Virometel Ltd. operates two distinct business units:

| Unit | Function |
|------|----------|
| **Eco-Depot** | Tank washing, repair, and storage for road tankers and ISO tanks |
| **Eco-Oil** | Industrial hazardous waste treatment and regulatory compliance |

### The Problem Being Solved
Before this system, all operations relied on:
- Dozens of separate Excel files per client
- Manual WhatsApp photo sharing between field workers and office staff
- Manual PDF generation for regulatory certificates
- No automated alerts for regulatory document expiry

---

## 🏗️ System Architecture

```
eco_oil_platform/
├── src/app/
│   ├── __init__.py          # Flask app factory
│   ├── db.py                # SQLAlchemy models (15+ entities)
│   └── routes.py            # All API endpoints (2,700+ lines)
├── data/
│   └── app.db               # SQLite database
├── output/
│   └── לקוחות/              # Auto-generated PDFs organized by client
├── artifacts/
│   └── templates/           # Official regulatory document templates (DOCX)
├── .streamlit/
│   └── config.toml          # Streamlit theme configuration
├── crew_analysis.py         # CrewAI multi-agent analysis system
├── dashboard.py             # Streamlit operational dashboard
├── email_agent_eco_oil.py   # Automated email dispatch agent
├── email_agent_eco_depot.py # Email parsing & PreArrival creation agent
├── vision_agent.py          # Computer vision identification agent
├── seed_demo_data.py        # Demo data loader (anonymized)
└── run.py                   # Flask server entry point
```

---

## 🔧 Tech Stack

| Technology | Purpose |
|-----------|---------|
| Python 3.14 + Flask | REST API server |
| SQLAlchemy + SQLite | Database ORM |
| ReportLab + python-bidi | Hebrew RTL PDF generation |
| docxtpl + LibreOffice | Official regulatory DOCX → PDF |
| Anthropic Claude API | AI agents & analysis |
| CrewAI | Multi-agent orchestration |
| Streamlit | Operational dashboard |
| schedule | Automated job scheduling |
| Git + GitHub | Version control (branch: master/dev) |

---

## 📦 Module 1 — Eco-Depot

Manages the complete lifecycle of road tankers and ISO tanks from arrival to release.

### Workflow
```
Client Request → Pre-Arrival → Gate Arrival → Compartment Setup
→ Wash Cycles → QC Check → Wash Certificate (PDF) → Release Document → Exit
```

### Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/clients` | Create client |
| POST | `/assets` | Register new asset |
| POST | `/depot/pre-arrivals` | Create pre-arrival request |
| PATCH | `/depot/pre-arrivals/<id>/arrive` | Mark asset as arrived |
| POST | `/depot/assets/<id>/compartments/setup` | Setup roadtanker compartments |
| POST | `/depot/assets/<id>/wash-cycles` | Start wash cycle |
| PATCH | `/depot/wash-cycles/<id>/complete` | Complete wash + auto-generate certificate |
| POST | `/depot/assets/<id>/repair-events` | Log repair event |
| POST | `/depot/assets/<id>/release-documents` | Issue release document |
| GET | `/depot/clients/<id>/portal` | Client portal (assets, certificates, status) |

### Auto-Generated Documents
- ✅ **Wash Certificate PDF** — Road tanker (with signature & stamp)
- ✅ **Wash Certificate PDF** — ISO tank
- ✅ **Release Document PDF** — ISO tank

---

## ☢️ Module 2 — Eco-Oil

Manages hazardous waste disposal events and full regulatory compliance lifecycle.

### Workflow
```
Producer Declaration → Agreement Document → Disposal Event
→ Close Event → Disposal Certificate (PDF) → Auto-Email to Client
```

### Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/eco-oil/producer-declarations` | Create producer declaration |
| GET | `/eco-oil/producer-declarations` | List all declarations |
| POST | `/eco-oil/agreements` | Create agreement document |
| GET | `/eco-oil/agreements` | List all agreements |
| GET | `/eco-oil/agreements/<id>/pdf` | Download agreement PDF |
| POST | `/eco-oil/disposal-events` | Create disposal event |
| PATCH | `/eco-oil/disposal-events/<id>/close` | Close event + auto-generate certificate |
| GET | `/eco-oil/disposal-events` | List disposal events |
| GET | `/eco-oil/disposal-certificates/<id>/pdf` | Download disposal certificate |
| GET | `/eco-oil/clients/<id>/portal` | Client portal (declarations, agreements, certificates) |

### Supported Waste Streams (11 streams)
`emulsion` · `base` · `acid` · `mineral (pit)` · `mineral (cube)` · `gasoil` · `washwater` · `sanitary` · `sanitary-eco` · `vegetable` · `concentrate`

### Regulatory Compliance Features
- ✅ Producer declarations with full Basel Convention codes (Y, H, R, D, Annex VIII)
- ✅ Agreement documents auto-generated from official Ministry of Environment templates
- ✅ Disposal certificates in Hebrew RTL format
- ✅ Expiry tracking with 30-day advance warnings
- ✅ Automated email alerts to clients before declaration expiry

---

## 🤖 AI Layer

### Agent 1 — Email Agent (Eco-Oil)
**File:** `email_agent_eco_oil.py`

- Runs automatically every Thursday at 12:00
- Fetches all unsent disposal certificates from the database
- Sends personalized emails to clients/carriers
- Checks for declarations expiring within 30 days
- Sends automated renewal reminders with client portal link
- Marks certificates as sent with timestamp

```bash
# Run immediately (demo mode)
python email_agent_eco_oil.py --now
```

### Agent 2 — Email Extraction Agent (Eco-Depot)
**File:** `email_agent_eco_depot.py`

- Reads incoming service request emails from Outlook (Microsoft 365)
- Uses Claude API to extract: asset identifier, chemical type, requested service
- Automatically creates Pre-Arrival records in the database
- Demo mode available for presentation

```bash
python email_agent_eco_depot.py
```

### Agent 3 — Gate Vision Agent
**File:** `vision_agent.py`

- Accepts a vehicle/tank image as input
- Uses Claude Vision API to identify license plate or container number
- Matches to existing asset in database
- Returns direct action links for wash cycles and photo uploads

```bash
# Demo mode
python vision_agent.py

# With real image
python vision_agent.py path/to/image.jpg
```

---

## 📊 Intelligence Layer — CrewAI

**File:** `crew_analysis.py`

Multi-agent analysis system operating on real operational data:

### Crew 1 — Data Analyst
- Ingests isotank and road tanker operational CSV data
- Validates data quality and identifies missing values
- Performs EDA: seasonal patterns, material distribution, duration analysis
- Generates management summary report

### Crew 2 — Data Scientist
- Analyzes problematic materials requiring multi-cycle washing
- Identifies cost anomalies and patterns
- Produces operational recommendations
- Compares performance across time periods

### Outputs
- `data/analysis_results.json` — Full analysis results
- Displayed in Streamlit dashboard under "AI Analysis" tab

---

## 📈 Streamlit Dashboard

**File:** `dashboard.py`

Three-tab operational dashboard:

| Tab | Content |
|-----|---------|
| 🧠 AI Analysis | CrewAI results — Data Analyst & Data Scientist crews |
| 🏭 Eco-Depot | Asset metrics, monthly charts, Pre-Arrival form, asset status lookup |
| ♻️ Eco-Oil | Waste stream overview, producer declaration form, agreements list with PDF download, expiry alerts |

```bash
streamlit run dashboard.py
```

---

## 🚀 Installation & Setup

```bash
# 1. Clone the repository
git clone https://github.com/lio2egs-cmyk/eco_oil_platform.git
cd eco_oil_platform

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start Flask server
python run.py

# 5. Load demo data (separate terminal)
python seed_demo_data.py

# 6. Launch dashboard (separate terminal)
streamlit run dashboard.py
```

The Flask API will be available at: `http://127.0.0.1:5000`  
The Streamlit dashboard will be available at: `http://localhost:8501`

---

## 📁 Demo Data

Run `seed_demo_data.py` to populate the database with anonymized demo data:

| Entity | Count |
|--------|-------|
| Eco-Oil clients | 15 |
| Producer declarations | 15 (including 3 expired, 3 expiring soon) |
| Agreement documents | 15 |
| Disposal events | 15 |
| Carriers | 3 |
| Eco-Depot clients | 5 |
| Assets (roadtankers + isotanks) | 14 |
| Pre-Arrival records | 10 |

---

## 📋 Development Status

| Component | Status |
|-----------|--------|
| Eco-Depot module | ✅ Complete |
| Eco-Oil module | ✅ Complete |
| Hebrew RTL PDF generation | ✅ Complete |
| Official regulatory DOCX templates | ✅ Complete |
| Email agents (both units) | ✅ Complete |
| Expiry warning system | ✅ Complete |
| Computer Vision agent | ✅ Complete |
| CrewAI analysis | ✅ Complete |
| Streamlit dashboard | ✅ Complete |
| Client portals (Depot + Oil) | ✅ Complete |
| Git workflow (master/dev) | ✅ Complete |

---

## 🔮 Roadmap (Post-Submission)

- Real Outlook/Microsoft 365 OAuth2 integration
- YOLO-based license plate recognition (replace Claude Vision)
- Mobile interface for field workers (tablet/handheld devices)
- Quarterly regulatory report to Ministry of Environment
- Accompanying transport form (טופס מלווה)
- Full real-data migration with client anonymization

---

## 👩‍💻 Developer

**Limor** — Operations Manager, Eco-Oil Arrow Virometel Ltd.  
Final Project — AI Development Course  
March 2026

> *"This system was built to solve real operational problems I face every day at work."*

---

## 📄 License

This project was developed as a university final project and is intended for internal use at Eco-Oil Arrow Virometel Ltd.
