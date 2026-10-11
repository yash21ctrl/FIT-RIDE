# FIT-RIDE — Enterprise Fleet Transit & Shared Vehicle Operating System
### PS 40 | Team KNIGHT

![FIT-RIDE Platform](https://img.shields.io/badge/Status-Production%20Ready-00d9f5?style=for-the-badge)
![Tests](https://img.shields.io/badge/PyTest-133%20Passed-32d583?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Backend-Flask%20REST%20API-000000?style=for-the-badge&logo=flask&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20GiST-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)

---

## 📌 Project Description

**FIT-RIDE** is an enterprise-grade transit operating system designed for corporate shared vehicle fleets. It automates end-to-end organizational vehicle booking, capacity allocation, driver dispatch, and route management without manual coordination bottlenecks or double-booking conflicts.

### Key Value Propositions
- **Zero Double-Bookings Guarantee**: Enforces mathematical non-overlap via PostgreSQL GiST exclusion constraints (`btree_gist`) using half-open time intervals `[start_time, blocked_until)` with mandatory 15-minute operational buffers.
- **Explainable Deterministic Engine**: 100% transparent algorithmic dispatch based on vehicle capacity matching, driver trip fairness, and fatigue safety standards. Zero non-deterministic AI hallucinations.
- **Strict Approval & Dispatch State Machine**: Routine requests require managerial sign-off before dispatches reach drivers. Drivers receive a real-time 5-minute countdown clock with synthesized audio alerts.
- **Unified Single-Page Landing Experience**: Consolidates Employee Booking, Driver Cockpit, Operations Command Console, and Photorealistic Fleet Exploration into a single high-performance web interface.
- **Audio Chime Alerts**: Built-in Web Audio API synthesizer generates pleasant and urgent notification tones directly in the browser with zero external audio assets or network dependencies.

---

## 🛠️ Technology Stack

### Backend Architecture
- **Language & Runtime**: Python 3.10+ (tested through Python 3.14)
- **Web Framework**: Flask Application Factory with modular Blueprints (`/api/auth`, `/api/bookings`, `/api/drivers`, `/api/vehicles`, `/api/manager`, `/api/trips`, `/api/analytics`, `/api/notifications`)
- **Database & Concurrency**: PostgreSQL with Supabase / psycopg2
  - GiST exclusion constraints on `tstzrange(start_time, blocked_until, '[)')`
  - In-memory thread-safe SQLite & mock fallbacks for zero-setup local testing
- **Authentication & Security**: Supabase JWT with SHA-256 / HS-256 tokens, server-enforced role verification from database profiles, defensive input bounds checking.
- **Timezone Awareness**: Localized strict handling for `Asia/Kolkata` (midnight-spanning daily hours, rest periods, operating hours).

### Deterministic Allocation Engine
- **Capacity Matching**: Evaluates vehicle seating against passenger counts, penalizing excess capacity to optimize utilization.
- **Fairness Scoring**: Balances driver workloads by favoring drivers with fewer completed trips today.
- **Driver Fatigue Standards**:
  - Maximum 9 hours driving per calendar day
  - Mandatory 45-minute rest gap between consecutive trips
  - Continuous driving capped at 4 hours
- **Conflict Handling**: Returns diagnosed failure reasons (`NO_VEHICLE_BIG_ENOUGH`, `ALL_VEHICLES_BUSY`, `NO_ELIGIBLE_DRIVER`) alongside automatic alternative time slots and priority waitlist queuing.

### Frontend Architecture
- **Unified Portal (`F2/index.html`)**: Single-page architecture with tab routing and deep linking (`?view=employee`, `?view=driver`, `?view=manager`, `?view=fleet`).
- **Styling & Design System**: Premium dark theme (`#080a0d`, `#121820`, `#00d9f5` cyan accent, `--radius: 22px`, `--shadow: 0 24px 80px rgba(0,0,0,0.34)`).
- **Audio Synthesis**: Pure Web Audio API oscillators producing dual-tone chime alerts ($D_5 \rightarrow A_5$) and urgent dispatch tones ($A_5 \rightarrow E_6$).
- **Visual Performance**: 235-frame hardware-accelerated canvas animation scrub and photorealistic vehicle assets for Toyota Innova Crysta, Force Tempo Traveller, Mahindra Scorpio, and Maruti Swift.

---

## 🚀 Setup & Run Instructions

### 1. Prerequisites
- **Python**: Version 3.10 or higher
- **Git**: Installed and available in PATH
- **Node.js** *(Optional)*: Version 18+ if running the static frame server separately

---

### 2. Clone the Repository
```bash
git clone https://github.com/yash21ctrl/FIT-RIDE.git
cd FIT-RIDE
```

---

### 3. Create and Activate Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

---

### 5. Configure Environment Variables *(Optional)*
The system includes built-in fallback configuration for local development. If connecting to a live Supabase instance, create a `.env` file in the root directory:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-or-service-key
SUPABASE_JWT_SECRET=your-jwt-secret
PORT=5000
```

---

### 6. Run the Application Server

Start the Flask backend:
```bash
python run.py
```
The server will start on **`http://127.0.0.1:5000`**.

Visit the application in your browser:
- **Unified Landing Page & Portals**: `http://127.0.0.1:5000/landing`
- **Employee Portal Direct**: `http://127.0.0.1:5000/landing?view=employee`
- **Driver Cockpit Direct**: `http://127.0.0.1:5000/landing?view=driver`
- **Operations Console Direct**: `http://127.0.0.1:5000/landing?view=manager`
- **Fleet Showcase Direct**: `http://127.0.0.1:5000/landing?view=fleet`

*(Optional) If running the standalone frontend Node.js server:*
```bash
node F2/server.js
```
Accessible at **`http://127.0.0.1:3100`**.

---

### 7. Run Automated Tests
Execute the comprehensive PyTest suite:
```bash
python -m pytest -v
```
**Test Results**: **133 passed**, 1 skipped, 0 failures across 12 test suites covering:
- Concurrency & exclusion locks (`test_conflicts.py`)
- Allocation engine rules & rest buffers (`test_engine.py`)
- State machine lifecycle transitions (`test_transitions.py`)
- Role authorization & security headers (`test_auth_roles.py`)
- Frontend rendering & API contracts (`test_f2_frontend.py`)
- Defensive input validation & boundaries (`test_defensive_enhancements.py`)

---

## 🔑 Enterprise Test Accounts

All pre-seeded test accounts use the password: **`123`**

| Role | User ID | Name | Department / Assignment |
| :--- | :--- | :--- | :--- |
| **Employee** | `emp1` | Ananya Roy | Engineering · Koramangala |
| **Employee** | `emp2` | Vikram Das | Sales Operations · Whitefield |
| **Employee** | `emp3` | Neha Nair | Product · Manyata Tech Park |
| **Employee** | `emp4` | Rahul Mehra | Finance · Electronic City |
| **Employee** | `emp5` | Sneha Patel | Operations · Indiranagar |
| **Driver** | `driver1` | Rajesh Kumar | Toyota Innova Crysta (KA-01-EA-1001) · ★ 4.9 |
| **Driver** | `driver2` | Suresh Patil | Maruti Swift Dzire (KA-01-EA-1004) · ★ 4.8 |
| **Driver** | `driver3` | Amit Singh | Force Tempo Traveller (KA-01-EA-1002) · ★ 4.7 |
| **Driver** | `driver4` | Priya Sharma | Mahindra Scorpio (KA-01-EA-1003) · ★ 4.6 |
| **Operations Manager** | `manager1` | Priya Sharma | Lead Operations Controller |
| **Operations Manager** | `manager2` | Kavana | Fleet Resource Manager |

---

## 🔄 End-to-End Operational Workflow

```
[Employee Portal]
       │
       ▼ (Submit Booking with Destination, Time, Passengers)
[Deterministic Allocation Engine]
       │ (Calculates Best-Fit Vehicle & Available Rested Driver)
       ▼
 [Status: PENDING] ──► Sits in Manager Approval Queue
                             │
                             ▼ (Manager Clicks "Approve Allocation")
                      [Status: DRIVER_PENDING]
                             │ (Audio Chime Sounds + 5-Min Timer Starts)
                             ▼
                     [Driver Cockpit]
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   Driver Accepts                     Driver Rejects/Times Out
            │                                 │
   [Status: CONFIRMED]                Re-runs Allocation Engine
            │                         Excluding that Driver
            ▼
   Driver Starts Trip
   [Status: IN_PROGRESS]
            │
            ▼
   Driver Completes Trip
   [Status: COMPLETED] ──► Vehicle & Driver Released to AVAILABLE
```

---

## 🛡️ License & Acknowledgements

Developed by **Team KNIGHT** for Problem Statement **PS 40**. Built for enterprise corporate transit operations with clean architecture, strict database-level concurrency, and human-first interface design.
