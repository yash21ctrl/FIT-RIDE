# Shared Vehicle Booking App (FIT-RIDE)
### Team KNIGHT | PS 40 | Software & Web Development

Deterministic fleet operations system for shared organizational vehicles. Guarantees **zero double-bookings** via PostgreSQL GiST exclusion constraints (`blocked_until`), soft-hold slot locking, plain-English decision reasoning, driver fatigue safety rules, and role-based web portals.

---

## 🌟 Key Architecture & Highlights

1. **Deterministic Allocation Engine**:
   - Zero AI/ML in the core. Pure, explainable rules-based selection.
   - Best-fit capacity matching, fairness trip balancing, driver fatigue guardrails.
   - 9-hour daily driving cap (`Asia/Kolkata` midnight-spanning), 45-min mandatory rest gap, 4-hour continuous driving limit.

2. **Absolute Zero Double-Bookings**:
   - Instant soft-hold locking on creation (`PENDING` state locks vehicle and driver).
   - PostgreSQL GiST exclusion constraints on `[start_time, blocked_until)`.
   - 15-minute buffer built into every reservation window.
   - Race conditions safely captured and formatted as friendly `VEHICLE_TAKEN` recommendations.

3. **Three Role-Based Portals**:
   - **Employee Portal** (`/employee`): Trip booking, plain-English algorithm explanations, failure ladder, waitlist join, cancel.
   - **Driver PWA** (`/driver`): Installable PWA, incoming trip cards with real-time countdown, mandatory rejection reasons, odometer & fuel logging, live GPS breadcrumbs.
   - **Manager Console** (`/manager`): Real-time approval queue, pure CSS Grid 24-hour Gantt chart, fleet and driver rosters, operational alerts, analytics, and 1-click Chaos Simulator.

4. **Edge Case Guardrails**:
   - **Emergency Bump Engine**: Emergency requests automatically bump low-priority bookings (`was_bumped=True`). Emergent trips dispatch directly with 2-minute response window. Bumped bookings can never be bumped again.
   - **Vehicle Maintenance Reallocation**: Flagging a vehicle for maintenance instantly reallocates all future slot-holding bookings to alternative vehicles or moves them to `WAITLISTED`.
   - **Waitlist Auto-Promotion**: Any slot-freeing event (`CANCELLED`, `COMPLETED`, `maintenance cleared`) auto-promotes waitlisted bookings strictly in priority order (`emergency > high > normal > low`).

---

## 🚀 Quick Start & Local Execution

### 1. Requirements
- Python 3.10+ (tested on Python 3.14)
- Pip dependencies installed:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Run the Application
```bash
python run.py
```
Server starts on `http://127.0.0.1:5000`.

### 3. Run the Automated Test Suite
```bash
python -m pytest -v
```
**116 passed unit and integration tests** verifying all business rules, concurrency constraints, state machine transitions, and edge cases.

### 4. Reset Demo State
To restore the fleet, drivers, and bookings to pristine initial seed condition at any time:
```bash
python -m scripts.reset_demo
```

---

## 🔑 Demo Accounts & Seed Credentials

All accounts use the standard password: `Password@123`

| Role | Email | Name | Key Feature / Test Persona |
| :--- | :--- | :--- | :--- |
| **Manager** | `manager1@fleetride.local` | Yashwanth M | Lead Operations Manager (Full Queue, Gantt, Chaos Simulator) |
| **Manager** | `manager2@fleetride.local` | Kavana | Fleet Controller (Fleet CRUD & Maintenance Toggles) |
| **Employee** | `emp1@fleetride.local` | Ananya Roy | Standard Employee (Scheduled Bookings) |
| **Employee** | `emp2@fleetride.local` | Vikram Das | Standard Employee (15-Pax Failure Test & Waitlist) |
| **Employee** | `emp3@fleetride.local` | Sneha Patel | Emergency Requester (Bump Engine) |
| **Driver** | `driver1@fleetride.local` | Ravi Kumar | Driver 1 (Recent Trip - Rest Gap Demo) |
| **Driver** | `driver2@fleetride.local` | Suresh Patil | Driver 2 (High Trips Today - Fairness Preference Demo) |
| **Driver** | `driver3@fleetride.local` | Amit Singh | Driver 3 (Available) |
| **Driver** | `driver4@fleetride.local` | Priya Sharma | Driver 4 (Available) |
| **Driver** | `driver5@fleetride.local` | Rajesh Verma | Driver 5 (Available) |

---

## 🎬 8-Step Demo Walkthrough (Section 16 Script)

1. **Manager Overview & CSS Grid Gantt (`/manager`)**:
   - Log in as `manager1@fleetride.local`.
   - Open **📊 Gantt Timeline** to view the full 24-hour visual schedule across all 6 fleet vehicles and 5 drivers.
   
2. **Standard Booking & Plain-English Reason (`/employee`)**:
   - Log in as `emp1@fleetride.local`.
   - Submit a request for 3 passengers to "Client Headquarters".
   - Notice the engine output explaining: *"Maruti Swift + Suresh Patil: seats 4 for 3 passengers (best fit), 0 trips today (fairness)..."*.
   - Manager approves -> Driver PWA receives alert with live countdown chime -> Driver accepts -> Employee notified.

3. **Overlapping Booking Handling**:
   - Submit a second request for the exact same time window.
   - The engine recognizes Maruti Swift is held and automatically allocates the next best available vehicle (Honda City).

4. **15-Passenger Failure Ladder**:
   - Submit a booking for 15 passengers.
   - The engine diagnoses `NO_VEHICLE_BIG_ENOUGH` (fleet max is 12 seats on Force Tempo Traveller).
   - Alternatives presented: Group split recommendation (2 vehicles) or tap **"Notify Me (Join Waitlist)"**.

5. **Concurrent Reservation Guard**:
   - Two concurrent threads attempt booking the same slot simultaneously.
   - Exactly one succeeds; the second catches exclusion constraint `23P01` and displays friendly recommendations (`VEHICLE_TAKEN`).

6. **Emergency Priority Bump**:
   - Toggle "Emergency Request" for 3 passengers when Swift is reserved by a low-priority booking.
   - System bumps the low-priority trip (`was_bumped=True`), dispatches emergency directly to driver with a 2-minute timer, and alerts the manager.

7. **Driver Fatigue & Auto-Reassignment**:
   - Driver opens incoming assignment on PWA and taps **Reject** with reason `"Tired / Fatigue"`.
   - Engine records rejection and immediately reassigns the trip to the next eligible rested driver.

8. **Vehicle Maintenance Reallocation**:
   - In Manager Console, flag **Mahindra Bolero** as `maintenance`.
   - System automatically reallocates future slot-holding trips on Bolero to alternative vehicles or transitions them to `WAITLISTED`.
   - Toggling Bolero back to `available` instantly auto-promotes waitlisted trips.

⚡ **Bonus - 1-Click Simulation**: Tap the **"⚡ Simulate Chaos"** button in the Manager Console header to run all 5 demonstration scenarios in real time!
