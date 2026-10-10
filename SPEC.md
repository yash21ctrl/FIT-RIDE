# SPEC.md: Shared Vehicle Booking App (Team KNIGHT | PS 40)

**App Name**: FleetRide / Fleet Operations System  
**Team**: KNIGHT | PS 40 | Software & Web Development | Panel: Kavana | Team Leader: Yashwanth M  
**Document**: System Specification & Implementation Guide

---

## 0. Working Rules & Constraints
1. **Spec in Repo**: Start every session by reading `SPEC.md` fully. Follow it exactly. If something is unclear, ask before guessing.
2. **One Phase at a Time**: Build step-by-step in phases. Do not build the whole app all at once.
3. **Engine Before UI**: The allocation engine must pass test scripts before any UI screen exists.
4. **Git Commit After Every Phase**: Commit with message `phase N done` so rollbacks are clean.
5. **No Silent Schema Changes**: Any schema change must be a new SQL migration file, explicitly explained.
6. **Error Diagnosis**: Explain root causes first, then fix without rewriting unrelated files.
7. **Secrets Management**: Secrets stay in `.env` (never committed). `.env.example` uses placeholder names.
8. **End of Phase Verification**: List all files created/modified and run acceptance tests.
9. **Protect the Demo Path**: Prioritize core demo features (Section 16) above cut-list items.
10. **Soft-Hold Architecture**: The engine reserves the vehicle and driver the moment a request is created (status `PENDING`). The database exclusion constraint blocks clashes from the first second.
11. **Constraint Buffer Fix**: SQL uses a `blocked_until` column (`end_time + buffer`), because Postgres does not allow expressions with intervals inside GiST exclusion constraints.
12. **Pure Deterministic Engine**: Plain Python with zero AI/ML in the core. Guaranteed correctness and full explainability.

---

## 1. The App at a Glance

### Overview
A fleet operations system for an organization's shared vehicles: booking, deterministic allocation, manager approval, driver acceptance via mobile PWA, trip execution with telemetry, and complete operational history.

* **Users**: Employees (request trips), Drivers (accept/reject & execute trips), Managers (review, approve, monitor, override).
* **Core Promise**: Never double-booked. Every trip gets a suitable vehicle and a rested driver, with a transparent decision explanation shown for each choice.
* **Two Booking Modes**:
  * **Scheduled**: Planned a day or week in advance (standard review/auto-approve flow, 30 min driver respond window).
  * **Emergency**: Right now, highest priority, skips approval queue, short 2 min driver response window, supports bumping low-priority trips.
* **Core Idea**: Deterministic rules-based allocation engine. The PostgreSQL database itself guarantees mutual exclusion via GiST exclusion constraints.
* **Stack**: Python + Flask backend, Supabase (Postgres, Auth, Realtime), Vanilla JS / responsive web frontend with three role views, Driver PWA, Leaflet + OpenStreetMap for live maps, Telegram bot for fallback dispatch alerts.

### Assumptions (Stated in Demo)
* Trip-based official travel, not daily staff commute.
* One trip uses exactly one vehicle and one driver.
* Every booking has a start and an end time (or duration).
* All times stored in UTC (`timestamptz`) and displayed in user's local timezone (`Asia/Kolkata`).
* Vehicles shared by employees of a single organization (single-tenant).

---

## 2. Roles and Permissions

| Action | Employee | Driver | Manager |
| :--- | :---: | :---: | :---: |
| Create a booking request | Yes | No | Yes (on behalf) |
| View own bookings | Yes | Yes (assigned only) | All |
| Cancel a booking | Own (before start) | No | Any (before start) |
| Approve, reject, override vehicle or driver | No | No | Yes |
| Accept or reject a trip | No | Own assignments only | No |
| Start and end a trip, log odometer & fuel | No | Own trips only | No |
| Share live GPS | No | Own trip in progress | No |
| View live trip location | Own trip | Own trip | All |
| Rate a trip | Own completed trip | No | No |
| Manage vehicles & drivers, set maintenance | No | No | Yes |
| View Gantt, history, analytics | No | No | Yes |
| Change config values | No | No | Yes |

> **Rule**: Every API endpoint checks the user's role from the verified Supabase JWT. Client-side button hiding is purely UX, never security.

---

## 3. Booking Statuses & Allowed Transitions

Status mutations are strictly centralized in a single state machine function:  
`transition(booking_id, new_status, actor, note=None)`

### State Machine Transition Matrix

| From | To | Who Triggers | Side Effects |
| :--- | :--- | :--- | :--- |
| `(new)` | `PENDING` | Employee, via engine | Vehicle & driver are soft-held. Manager notified. |
| `(new)` | `WAITLISTED` | Engine | No vehicle assigned. Employee notified with reason and alternatives. |
| `PENDING` | `APPROVED` | Manager or auto-approve rule | Logged in `decision_log`. Immediately moves to `DRIVER_PENDING`. |
| `PENDING` | `REJECTED` | Manager | Slot released. Employee notified with reason. Waitlist re-check runs. |
| `APPROVED` | `DRIVER_PENDING` | System, immediately | `respond_by` set. Driver notified. |
| `DRIVER_PENDING` | `CONFIRMED` | Driver accepts | Employee and manager notified. |
| `DRIVER_PENDING` | `PENDING` | Driver rejects or times out | Reason logged in `driver_responses`. Engine re-runs excluding that driver. If none, failure ladder runs. |
| `CONFIRMED` | `IN_PROGRESS` | Driver starts trip | Driver status becomes `on_trip`. Live GPS begins. |
| `IN_PROGRESS` | `COMPLETED` | Driver ends trip | Odometer & fuel logged. Driver & vehicle freed (`available`). Rating requested. Waitlist re-check runs. |
| `PENDING`, `APPROVED`, `DRIVER_PENDING`, `CONFIRMED` | `CANCELLED` | Employee or manager | Slot released. Waitlist re-check runs. |
| `PENDING`, `APPROVED`, `DRIVER_PENDING`, `CONFIRMED` | `BUMPED` | Engine (Emergency) | Slot released. Candidate flagged `was_bumped=True`. Bumped employee notified with alternatives. Manager alerted. |
| `BUMPED` | `PENDING` or `WAITLISTED` | Employee picks alternative / engine finds none | `was_bumped=True` preserved so booking cannot be bumped again. |
| `WAITLISTED` | `PENDING` | Engine, when capacity frees up | Employee notified. Normal approval flow resumes. |

### Slot Reservation Semantics
* **Statuses holding a slot**: `PENDING`, `APPROVED`, `DRIVER_PENDING`, `CONFIRMED`, `IN_PROGRESS`.
* **Statuses releasing a slot**: `REJECTED`, `CANCELLED`, `BUMPED`, `COMPLETED`, `WAITLISTED`.
* **Soft-Hold Rule**: On creation, a booking is inserted with selected `vehicle_id` and `driver_id` in status `PENDING`. Postgres exclusion constraint blocks overlapping slots immediately.

---

## 4. App Flows

### 4.1 Scheduled Booking
1. Employee fills form: date, start time, end time (or duration), destination, passenger count, reason, type = `scheduled`.
2. Frontend converts local time to UTC; sends `POST /api/bookings` with idempotency guard (button disabled, duplicate request check within 30s).
3. Backend validates input (passengers 1–60, start in future, end after start).
4. Backend runs `allocate()`. On success, inserts booking as `PENDING` with top candidate, sets `blocked_until = end_time + buffer_minutes`, writes `decision_reason`, returns top 3 options.
5. If auto-approve rule matches (`scheduled`, priority `low`/`normal`, duration <= `auto_approve_max_hours`, within `working_hours`), status transitions automatically to `APPROVED` then `DRIVER_PENDING`. Otherwise, awaits manager.
6. Manager reviews in approval queue, approves, overrides vehicle/driver, or rejects.
7. Upon approval, moves to `DRIVER_PENDING` with `respond_by` timestamp. Driver notified.
8. Driver accepts -> `CONFIRMED`. Driver starts -> `IN_PROGRESS`. Driver ends -> `COMPLETED`.

### 4.2 Driver Response & Timeout
1. Driver receives alert. Countdown timer ticks down from `respond_by` (Scheduled: 30 min, Emergency: 2 min).
2. Driver accepts, or rejects with mandatory reason: `tired`, `vehicle_issue`, `personal`, `too_far`, `unsafe`, `other`.
3. Background job runs every 30 seconds. Expired `DRIVER_PENDING` bookings log `timeout` in `driver_responses` and re-run `allocate()` excluding timed-out driver.
4. If next driver found, booking resets to `DRIVER_PENDING` with new driver and fresh countdown. If no driver left, escalates to manager.
5. A `vehicle_issue` rejection flags the vehicle for manager inspection.

### 4.3 Emergency Booking
1. Employee submits type = `emergency`, priority = `emergency`, reason mandatory.
2. Engine tries normal allocation first (free vehicle, rested driver, 2 min driver response window).
3. If no candidate free, engine searches for a bump candidate: overlapping booking with priority `low`, status not `IN_PROGRESS`, not already `was_bumped`, vehicle capacity >= passengers. Lowest priority picked first, then most recently created.
4. Candidate transitions to `BUMPED` (`was_bumped = True`). Emergency takes the slot. Bumped employee receives alternatives or waitlist placement. Manager alerted.
5. Emergencies skip manager queue and enter `DRIVER_PENDING` directly.
6. Guardrails: Never bump `IN_PROGRESS` or `emergency` trips. Never bump a booking twice.

### 4.4 Failure Ladder (When Allocation Finds Nothing)
1. **Diagnose Reason**:
   * `NO_VEHICLE_BIG_ENOUGH`: No vehicle in fleet has >= requested seats.
   * `ALL_VEHICLES_BUSY`: Every suitable vehicle has overlapping bookings.
   * `NO_ELIGIBLE_DRIVER`: Vehicles available, but drivers off duty, over daily hours, or lack required rest.
   * `VEHICLES_IN_MAINTENANCE`: All suitable vehicles marked under maintenance.
2. **Offer Alternatives**:
   * Next free slot per suitable vehicle within 7 days.
   * Shifted windows (+/- 30, 60, 90, 120 minutes).
   * Shorter duration options.
3. **Waitlist with Auto-Promotion**: Employee taps "Notify me" -> status `WAITLISTED`. Any freeing event (cancel, reject, trip complete, maintenance cleared) triggers `promote_waitlisted()` which re-runs allocation in order of priority, then request time.
4. **Bump**: Triggered if emergency.
5. **Escalate to Manager**: Manager can manually override, grant driver extra hours (logged as exception), or arrange external cab.
6. **Graceful Failure**: Never half-confirm. Show clear user-friendly explanation.

### 4.5 Trip Lifecycle
1. Driver taps **Start**: logs starting odometer, ticks checklist. Status becomes `IN_PROGRESS`.
2. Driver app broadcasts GPS every 5–10s on Supabase Realtime channel `trip:{id}`. Batched points POSTed to `/api/trips/{id}/location` every 60s and at trip conclusion.
3. Driver taps **End**: logs end odometer and fuel added. Status becomes `COMPLETED`. Vehicle and driver set to `available`. Triggers waitlist promotion.
4. Employee prompted for rating: driver 1–5, vehicle 1–5, tags, optional comment.

### 4.6 Vehicle Maintenance
1. Manager flags vehicle as `maintenance` (optional `maintenance_until` datetime).
2. System queries all future slot-holding bookings on that vehicle. For each, re-runs `allocate()`. Reassigns if alternate found; marks `WAITLISTED` and alerts manager if none.

### 4.7 Race Conditions & Conflict Handling
* Database exclusion constraint rejects simultaneous inserts/updates for the same vehicle/driver with Postgres code `23P01`.
* Application catches `23P01` and returns friendly payload:
  `{ "error": { "code": "VEHICLE_TAKEN", "message": "That vehicle was just reserved. Here are the best alternatives:", "alternatives": [...] } }`

---

## 5. Project Directory Structure

```
fleet-app/
│── SPEC.md
│── .env.example
│── requirements.txt
│── run.py
│── app/
│   ├── __init__.py           # Flask app factory, blueprints registration
│   ├── config.py             # Loads environment vars and app_config values
│   ├── db.py                 # Supabase and Postgres psycopg2 client helpers
│   ├── auth.py               # JWT verification, @require_role decorator
│   ├── engine/
│   │   ├── allocate.py       # allocate(), driver_ok(), score(), explain()
│   │   ├── alternatives.py   # Free-slot search and shifted window generator
│   │   ├── bump.py           # Emergency bump candidate selection and logic
│   │   └── waitlist.py       # promote_waitlisted() auto-promotion engine
│   ├── services/
│   │   ├── transitions.py    # transition() state machine and audit logger
│   │   ├── notifications.py  # In-app, Realtime, push, and Telegram alerts
│   │   └── timeouts.py       # Driver response APScheduler timeout job
│   └── routes/
│       ├── bookings.py       # Employee booking endpoints
│       ├── vehicles.py       # Vehicle management CRUD
│       ├── drivers.py        # Driver management CRUD & accept/reject
│       ├── trips.py          # Trip start, end, telemetry, ratings
│       ├── manager.py        # Queue, approve, override, reject, Gantt
│       ├── analytics.py      # Utilization, fairness, rejection metrics
│       └── ratings.py        # Trip rating submissions
│── migrations/
│   ├── 001_schema.sql        # Tables, enums, extensions
│   ├── 002_constraints.sql   # GiST exclusion constraints with blocked_until
│   └── 003_seed.sql          # 6 vehicles, 5 drivers, 5 employees, 2 managers, starter bookings
│── scripts/
│   ├── apply_migrations.py   # Applies SQL migrations to DATABASE_URL
│   ├── reset_demo.py         # Resets database to pristine seed state
│   └── try_allocate.py       # CLI smoke test for allocation engine
│── tests/
│   ├── test_engine.py        # Comprehensive allocation unit tests
│   ├── test_transitions.py   # State machine transition rule tests
│   └── test_conflicts.py     # Concurrent multi-threaded race condition tests
└── frontend/                 # Static web portal and Driver PWA
    ├── shared/               # API client, auth helper, time conversion, realtime
    ├── employee/             # Employee booking and tracking UI
    ├── driver/               # Mobile-first Driver PWA (manifest, sw.js)
    └── manager/              # Manager operations dashboard, approval queue, Gantt
```

---

## 6. Database Schema (Supabase / PostgreSQL)

### Extensions & Types
```sql
create extension if not exists btree_gist;

create type user_role as enum ('employee','driver','manager');
create type vehicle_status as enum ('available','maintenance','retired');
create type driver_status as enum ('off','available','on_trip','break');
create type booking_type as enum ('scheduled','emergency');
create type booking_priority as enum ('low','normal','high','emergency');
create type booking_status as enum (
  'PENDING','APPROVED','DRIVER_PENDING','CONFIRMED',
  'IN_PROGRESS','COMPLETED','REJECTED','CANCELLED','BUMPED','WAITLISTED'
);
```

### Tables
```sql
create table profiles (
  id uuid primary key references auth.users(id),
  name text not null,
  role user_role not null,
  phone text,
  telegram_chat_id text
);

create table vehicles (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  type text not null, -- car, van, minibus
  capacity int not null check (capacity > 0),
  status vehicle_status not null default 'available',
  maintenance_until timestamptz,
  odometer_km numeric default 0
);

create table drivers (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id),
  status driver_status not null default 'available',
  license_no text,
  rating_avg numeric default 0
);

create table bookings (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references profiles(id),
  vehicle_id uuid references vehicles(id),
  driver_id uuid references drivers(id),
  start_time timestamptz not null,
  end_time timestamptz not null,
  blocked_until timestamptz not null, -- end_time + buffer (set by app)
  destination text not null,
  dest_lat double precision,
  dest_lng double precision,
  passengers int not null check (passengers between 1 and 60),
  reason text not null,
  type booking_type not null default 'scheduled',
  priority booking_priority not null default 'normal',
  status booking_status not null default 'PENDING',
  decision_reason text,
  failure_reason text,
  respond_by timestamptz,
  was_bumped boolean not null default false,
  created_at timestamptz not null default now(),
  check (end_time > start_time),
  check (blocked_until >= end_time)
);

-- Core GiST Exclusion Constraints: No overlapping slots for active bookings
alter table bookings add constraint no_vehicle_overlap
exclude using gist (
  vehicle_id with =,
  tstzrange(start_time, blocked_until, '[)') with &&
)
where (
  vehicle_id is not null and status in (
    'PENDING','APPROVED','DRIVER_PENDING','CONFIRMED','IN_PROGRESS'
  )
);

alter table bookings add constraint no_driver_overlap
exclude using gist (
  driver_id with =,
  tstzrange(start_time, blocked_until, '[)') with &&
)
where (
  driver_id is not null and status in (
    'PENDING','APPROVED','DRIVER_PENDING','CONFIRMED','IN_PROGRESS'
  )
);

create table driver_responses (
  id uuid primary key default gen_random_uuid(),
  booking_id uuid not null references bookings(id),
  driver_id uuid not null references drivers(id),
  response text not null check (response in ('accepted','rejected','timeout')),
  reject_reason text check (reject_reason in ('tired','vehicle_issue','personal','too_far','unsafe','other')),
  responded_at timestamptz not null default now()
);

create table decision_log (
  id uuid primary key default gen_random_uuid(),
  booking_id uuid references bookings(id),
  actor_id uuid references profiles(id),
  action text not null, -- approved, overridden, rejected, bumped, auto_approved, exception
  note text,
  created_at timestamptz not null default now()
);

create table trips (
  id uuid primary key default gen_random_uuid(),
  booking_id uuid not null unique references bookings(id),
  start_odometer numeric,
  end_odometer numeric,
  fuel_added numeric,
  checklist jsonb,
  actual_start timestamptz,
  actual_end timestamptz
);

create table trip_locations (
  id bigserial primary key,
  trip_id uuid not null references trips(id),
  lat double precision not null,
  lng double precision not null,
  recorded_at timestamptz not null default now()
);

create table ratings (
  id uuid primary key default gen_random_uuid(),
  trip_id uuid not null unique references trips(id),
  rated_by uuid not null references profiles(id),
  driver_rating int check (driver_rating between 1 and 5),
  vehicle_rating int check (vehicle_rating between 1 and 5),
  tags text[],
  comment text
);

create table notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id),
  message text not null,
  booking_id uuid references bookings(id),
  channel text not null default 'in_app',
  read boolean not null default false,
  created_at timestamptz not null default now()
);

create table app_config (
  key text primary key,
  value text not null
);
```

### Row Level Security (RLS)
Enable RLS on `bookings`, `notifications`, and `trip_locations`. Read policies allow users to read only appropriate records (employees: own bookings; drivers: assigned bookings; managers: all). Writes are processed via the backend using authenticated user contexts.

---

## 7. App Configuration Values (`app_config`)

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `buffer_minutes` | `15` | Gap kept after every trip for cleaning/inspection |
| `driver_max_hours_per_day` | `9` | Daily driving cap |
| `driver_min_rest_minutes` | `45` | Minimum rest gap between trips for a driver |
| `driver_max_continuous_hours`| `4` | Maximum continuous driving before a mandatory long break |
| `driver_long_break_minutes` | `30` | Duration required for the continuous driving break |
| `respond_window_scheduled_min` | `30` | Driver response timeout window for scheduled bookings |
| `respond_window_emergency_min` | `2` | Driver response timeout window for emergency bookings |
| `auto_approve_max_hours` | `4` | Maximum trip duration for auto-approval rule |
| `working_hours` | `08:00-20:00` | Working hours interval for auto-approval |
| `merge_radius_km` | `10` | Haversine distance threshold for trip merge recommendations |
| `timezone` | `Asia/Kolkata` | Base display and driver day boundary timezone |

---

## 8. Allocation Engine Specification

### 8.1 Interface
```python
allocate(request, exclude_driver_ids=(), exclude_booking_id=None) -> AllocationResult
```
* **Request Object**: `start`, `end`, `passengers`, `type`, `priority`, `dest_lat`, `dest_lng`, `employee_id`
* **AllocationResult**: `ok` (bool), `options` (list of up to 3), `failure_reason` (str or None), `alternatives` (list)
* **Option**: `vehicle_id`, `driver_id`, `score`, `reason` (str), `skipped` (list of strings explaining unselected candidates)

### 8.2 Execution Steps
1. Compute `blocked_until = end + buffer_minutes`.
2. **Vehicle Filtering**:
   * Status must be `available`.
   * Not in maintenance during the window `[start, blocked_until)`.
   * `capacity >= passengers`.
   * If no vehicle has enough seats: failure `NO_VEHICLE_BIG_ENOUGH`.
   * If all matching vehicles are under maintenance: `VEHICLES_IN_MAINTENANCE`.
3. **Vehicle Conflict Filtering**:
   * Drop vehicles with an existing slot-holding booking overlapping `[start, blocked_until)`:  
     `existing.start < new.blocked_until AND new.start < existing.blocked_until`.
   * Ignore `exclude_booking_id`.
   * If zero vehicles remain: failure `ALL_VEHICLES_BUSY`.
4. **Driver Eligibility (`driver_ok`)**:
   * Driver status is not `off`.
   * Driver not in `exclude_driver_ids`.
   * No overlapping booking in `[start, blocked_until)`.
   * Total hours driven in the driver's local day (`Asia/Kolkata`) + this trip <= `driver_max_hours_per_day` (9 hrs).
   * Rest gap since last completed trip end >= `driver_min_rest_minutes` (45 min).
   * Continuous driving (consecutive trips with gaps < `driver_long_break_minutes`) does not exceed `driver_max_continuous_hours` (4 hrs).
   * If no drivers pass for any viable vehicle: failure `NO_ELIGIBLE_DRIVER`.
5. **Scoring Function**:
   ```python
   SCORING_WEIGHTS = {
       "capacity_penalty": -2.0,   # Best fit: smaller excess capacity preferred
       "fairness_multiplier": 3.0, # Fewer trips today favored: 3 * (avg_trips_today - driver.trips_today)
       "rating_multiplier": 0.5,   # Tie breaker: 0.5 * rating_avg
       "merge_bonus": 5.0          # Optional proximity trip-merge bonus
   }
   ```
6. **Result Formatting**:
   * Sort pairs by score descending.
   * Return top 3 options with human-readable reason strings and detailed skipped candidates list.

---

## 9. API Endpoints

All endpoints verify Supabase JWT in the `Authorization: Bearer <token>` header and enforce role authorization.

### Standardized Error Format
```json
{
  "error": {
    "code": "VEHICLE_TAKEN",
    "message": "That vehicle was just reserved. Here are the best alternatives:",
    "alternatives": []
  }
}
```

### Endpoints Table

| Method & Path | Role | Purpose |
| :--- | :--- | :--- |
| `POST /api/auth/login` | Any | Authenticate via Supabase Auth, return profile & role |
| `GET /api/me` | Any | Return profile and role of authenticated user |
| `POST /api/bookings` | Employee, Manager | Submit booking request, run engine, return top 3 or failure alternatives |
| `GET /api/bookings/mine` | Employee | Return personal booking history & status |
| `POST /api/bookings/{id}/cancel` | Employee, Manager | Cancel booking, release slot, trigger waitlist promotion |
| `POST /api/bookings/{id}/choose-alternative` | Employee | Confirm alternative option after failure or bump |
| `POST /api/bookings/{id}/waitlist` | Employee | Join waitlist for unmet request |
| `GET /api/manager/queue` | Manager | Fetch pending approval queue with decision explanations |
| `POST /api/manager/bookings/{id}/approve` | Manager | Approve booking, advance to `DRIVER_PENDING` |
| `POST /api/manager/bookings/{id}/override` | Manager | Override vehicle or driver assignment, validating constraints |
| `POST /api/manager/bookings/{id}/reject` | Manager | Reject booking with mandatory reason |
| `GET /api/driver/requests` | Driver | Fetch incoming `DRIVER_PENDING` bookings |
| `POST /api/driver/bookings/{id}/accept` | Driver | Accept assigned trip -> `CONFIRMED` |
| `POST /api/driver/bookings/{id}/reject` | Driver | Reject trip with mandatory reason from allowed list |
| `POST /api/trips/{booking_id}/start` | Driver | Start trip: log starting odometer & checklist -> `IN_PROGRESS` |
| `POST /api/trips/{booking_id}/end` | Driver | End trip: log end odometer & fuel -> `COMPLETED`, trigger waitlist |
| `POST /api/trips/{id}/location` | Driver | Ingest batched GPS coordinates |
| `POST /api/trips/{id}/rate` | Employee | Submit driver & vehicle rating (1–5) and review |
| `GET/POST/PATCH /api/vehicles` | Manager | Fleet vehicle CRUD & maintenance status toggles |
| `GET/POST/PATCH /api/drivers` | Manager | Driver management CRUD |
| `GET /api/manager/gantt?from=&to=` | Manager | Bookings organized per vehicle and driver for Gantt visualizer |
| `GET /api/manager/history` | Manager | Filterable booking audit trail |
| `GET /api/manager/analytics` | Manager | Vehicle utilization, driver trip fairness, reject reasons |
| `GET /api/notifications` | Any | Fetch user notifications |
| `POST /api/notifications/{id}/read` | Any | Mark notification as read |
| `POST /api/admin/simulate` | Manager | Trigger demo chaos script (overlapping trips, bump, tired reject) |
| `POST /api/telegram/webhook` | Bot | Telegram webhook to link user chat and dispatch alerts |

---

## 10. Phase-by-Phase Build Plan

| Phase | Description | Tier |
| :---: | :--- | :---: |
| **0** | Project Setup, SPEC in repo, Environment | **Must** |
| **1** | Database: Schema, Constraints, Seed Data | **Must** |
| **2** | Allocation Engine & Unit Tests (No UI) | **Must** |
| **3** | Flask App, Auth, Roles, API Skeleton | **Must** |
| **4** | Booking Flow APIs & State Machine | **Must** |
| **5** | Employee Portal (Request Form, Suggestions, Realtime) | **Must** |
| **6** | Driver PWA (Incoming Cards, Accept/Reject, Start/End) | **Must** |
| **7** | Manager Dashboard, Approval Queue, CSS Grid Gantt | **Must** |
| **8** | Notifications, Telegram Bot, Driver Timeout Job | **Strong** |
| **9** | Edge Cases: Failure Ladder, Waitlist Promotion, Bump | **Strong** |
| **10** | Live GPS Telemetry, Ratings, Odometer & Fuel | **Stretch** |
| **11** | Analytics, Demo Chaos Simulator, Trip Merging | **Stretch** |
| **12** | Production Deployment, Data Reset Script, Rehearsal | **Must** |

---

## 11. Seed Data Specifications (Phase 1)

### Fleet Vehicles
1. **Maruti Swift**: 4 seats (Car)
2. **Honda City**: 4 seats (Car)
3. **Maruti Ertiga**: 7 seats (MUV)
4. **Toyota Innova Crysta**: 7 seats (MUV)
5. **Mahindra Bolero**: 7 seats (MUV - reserved for maintenance demo)
6. **Force Tempo Traveller**: 12 seats (Minibus - largest, used to test 15-passenger failure)

### People & Roles
* **5 Drivers**:
  * Driver 1: Completed trip recently (used to demonstrate 45 min rest-gap violation).
  * Driver 2: High trip count today (demonstrates fairness algorithm favoring others).
  * Drivers 3, 4, 5: Available, normal status.
* **5 Employees**: Standard employee accounts for booking tests.
* **2 Managers**: Administrative accounts with approval and override privileges.

---

## 12. Complete Demo Script (Section 16)
1. **Manager Overview**: Open manager portal; show 6 fleet vehicles and CSS Grid Gantt chart.
2. **Standard Booking**: Employee books trip; system displays plain-English selection rationale; manager approves; driver receives push/realtime alert and accepts; employee notified.
3. **Overlapping Booking**: Employee submits overlapping request; system automatically assigns alternative suitable vehicle.
4. **15-Person Failure Ladder**: Submit 15-passenger booking. System diagnoses `NO_VEHICLE_BIG_ENOUGH`, presents alternatives, employee joins waitlist. A cancellation auto-promotes the waitlisted trip.
5. **Concurrent Reservation Guard**: Two sessions attempt booking same slot simultaneously; exactly one succeeds, the second catches `23P01` and displays friendly alternative recommendations.
6. **Emergency Priority Bump**: Emergency request submitted; system bumps low-priority scheduled trip; alerts bumped employee and manager.
7. **Driver Fatigue & Reassignment**: Driver rejects with "too tired"; engine immediately re-assigns to next eligible driver; analytics charts update.
8. **Vehicle Maintenance**: Manager flags Bolero as maintenance; all future trips automatically reallocated or waitlisted.
9. **Trip Execution**: Driver starts trip with odometer reading; live map traces location; driver completes trip; employee rates trip.
