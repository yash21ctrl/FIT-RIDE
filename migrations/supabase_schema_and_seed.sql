-- ============================================================================
-- FleetRide: Complete Supabase Schema, GiST Constraints & Seed Data
-- Run this directly in Supabase SQL Editor:
-- https://supabase.com/dashboard/project/jppqpvhpwoarecqghkyl/sql/new
-- ============================================================================

-- 1. Enable Required PostgreSQL Extensions
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- 2. Domain ENUM Types
DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('employee', 'driver', 'manager');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE vehicle_status AS ENUM ('available', 'maintenance', 'retired');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE driver_status AS ENUM ('off', 'available', 'on_trip', 'break');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE booking_type AS ENUM ('scheduled', 'emergency');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE booking_priority AS ENUM ('low', 'normal', 'high', 'emergency');
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  CREATE TYPE booking_status AS ENUM (
    'PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED',
    'IN_PROGRESS', 'COMPLETED', 'REJECTED', 'CANCELLED', 'BUMPED', 'WAITLISTED'
  );
EXCEPTION WHEN duplicate_object THEN null; END $$;

-- 3. Domain Tables

-- Profiles Table (Users)
CREATE TABLE IF NOT EXISTS profiles (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  role user_role NOT NULL,
  email text,
  phone text,
  telegram_chat_id text
);

-- Vehicles Table (Fleet)
CREATE TABLE IF NOT EXISTS vehicles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  type text NOT NULL, -- car, van, minibus
  capacity int NOT NULL CHECK (capacity > 0),
  status vehicle_status NOT NULL DEFAULT 'available',
  maintenance_until timestamptz,
  odometer_km numeric DEFAULT 0
);

-- Drivers Table (Roster)
CREATE TABLE IF NOT EXISTS drivers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status driver_status NOT NULL DEFAULT 'available',
  license_no text,
  rating_avg numeric DEFAULT 0
);

-- Bookings Table
CREATE TABLE IF NOT EXISTS bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id uuid NOT NULL REFERENCES profiles(id),
  vehicle_id uuid REFERENCES vehicles(id),
  driver_id uuid REFERENCES drivers(id),
  start_time timestamptz NOT NULL,
  end_time timestamptz NOT NULL,
  blocked_until timestamptz NOT NULL,
  destination text NOT NULL,
  dest_lat double precision,
  dest_lng double precision,
  passengers int NOT NULL CHECK (passengers BETWEEN 1 AND 60),
  reason text NOT NULL,
  type booking_type NOT NULL DEFAULT 'scheduled',
  priority booking_priority NOT NULL DEFAULT 'normal',
  status booking_status NOT NULL DEFAULT 'PENDING',
  decision_reason text,
  failure_reason text,
  respond_by timestamptz,
  was_bumped boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (end_time > start_time),
  CHECK (blocked_until >= end_time)
);

-- Driver Responses
CREATE TABLE IF NOT EXISTS driver_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  driver_id uuid NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
  response text NOT NULL CHECK (response IN ('accepted', 'rejected', 'timeout')),
  reject_reason text CHECK (reject_reason IN ('tired', 'vehicle_issue', 'personal', 'too_far', 'unsafe', 'other')),
  responded_at timestamptz NOT NULL DEFAULT now()
);

-- Decision Log
CREATE TABLE IF NOT EXISTS decision_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid REFERENCES bookings(id) ON DELETE CASCADE,
  actor_id uuid REFERENCES profiles(id),
  action text NOT NULL,
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Trips Table
CREATE TABLE IF NOT EXISTS trips (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
  start_odometer numeric,
  end_odometer numeric,
  fuel_added numeric,
  checklist jsonb,
  actual_start timestamptz,
  actual_end timestamptz
);

-- Telemetry Breadcrumbs
CREATE TABLE IF NOT EXISTS trip_locations (
  id bigserial PRIMARY KEY,
  trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now()
);

-- Ratings
CREATE TABLE IF NOT EXISTS ratings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  trip_id uuid NOT NULL UNIQUE REFERENCES trips(id) ON DELETE CASCADE,
  rated_by uuid NOT NULL REFERENCES profiles(id),
  driver_rating int CHECK (driver_rating BETWEEN 1 AND 5),
  vehicle_rating int CHECK (vehicle_rating BETWEEN 1 AND 5),
  tags text[],
  comment text
);

-- Notifications
CREATE TABLE IF NOT EXISTS notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  message text NOT NULL,
  booking_id uuid REFERENCES bookings(id) ON DELETE SET NULL,
  channel text NOT NULL DEFAULT 'in_app',
  read boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- System Config Key-Value store
CREATE TABLE IF NOT EXISTS app_config (
  key text PRIMARY KEY,
  value text NOT NULL
);

-- 4. GiST Exclusion Constraints (Zero Double-Booking Guarantee)
DO $$ BEGIN
  ALTER TABLE bookings ADD CONSTRAINT no_vehicle_overlap
  EXCLUDE USING gist (
    vehicle_id WITH =,
    tstzrange(start_time, blocked_until, '[)') WITH &&
  )
  WHERE (
    vehicle_id IS NOT NULL AND status IN (
      'PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED', 'IN_PROGRESS'
    )
  );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
  ALTER TABLE bookings ADD CONSTRAINT no_driver_overlap
  EXCLUDE USING gist (
    driver_id WITH =,
    tstzrange(start_time, blocked_until, '[)') WITH &&
  )
  WHERE (
    driver_id IS NOT NULL AND status IN (
      'PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED', 'IN_PROGRESS'
    )
  );
EXCEPTION WHEN duplicate_object THEN null; END $$;

-- 5. System Configuration Values
INSERT INTO app_config (key, value) VALUES
  ('buffer_minutes', '15'),
  ('driver_max_hours_per_day', '9'),
  ('driver_min_rest_minutes', '45'),
  ('driver_max_continuous_hours', '4'),
  ('driver_long_break_minutes', '30'),
  ('respond_window_scheduled_min', '30'),
  ('respond_window_emergency_min', '2'),
  ('auto_approve_max_hours', '4'),
  ('working_hours', '08:00-20:00'),
  ('merge_radius_km', '10'),
  ('timezone', 'Asia/Kolkata')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 6. Fleet Vehicles (1 Bus, 2 Cars, 2 Vans)
INSERT INTO vehicles (id, name, type, capacity, status, maintenance_until, odometer_km) VALUES
  ('00000000-0000-0000-0001-000000000001', 'Maruti Swift', 'car', 4, 'available', NULL, 12500),
  ('00000000-0000-0000-0001-000000000002', 'Honda City', 'car', 4, 'available', NULL, 28400),
  ('00000000-0000-0000-0001-000000000004', 'Toyota Innova Crysta', 'van', 6, 'available', NULL, 61000),
  ('00000000-0000-0000-0001-000000000005', 'Mahindra Bolero', 'van', 6, 'available', NULL, 78300),
  ('00000000-0000-0000-0001-000000000006', 'Force Tempo Traveller', 'minibus', 12, 'available', NULL, 94000)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  type = EXCLUDED.type,
  capacity = EXCLUDED.capacity,
  status = EXCLUDED.status;

-- 7. Seed Profiles (Managers, Employees, Drivers)
INSERT INTO profiles (id, name, role, email, phone, telegram_chat_id) VALUES
  ('00000000-0000-0000-0002-000000000001', 'Yashwanth M', 'manager', 'manager1@fleetride.local', '+919876543210', 'demo_mgr_1'),
  ('00000000-0000-0000-0002-000000000002', 'Kavana', 'manager', 'manager2@fleetride.local', '+919876543211', 'demo_mgr_2'),
  ('00000000-0000-0000-0003-000000000001', 'Ananya Roy', 'employee', 'emp1@fleetride.local', '+919876543220', 'demo_emp_1'),
  ('00000000-0000-0000-0003-000000000002', 'Vikram Das', 'employee', 'emp2@fleetride.local', '+919876543221', 'demo_emp_2'),
  ('00000000-0000-0000-0003-000000000003', 'Neha Nair', 'employee', 'emp3@fleetride.local', '+919876543222', 'demo_emp_3'),
  ('00000000-0000-0000-0003-000000000004', 'Rahul Mehra', 'employee', 'emp4@fleetride.local', '+919876543223', 'demo_emp_4'),
  ('00000000-0000-0000-0003-000000000005', 'Sneha Patel', 'employee', 'emp5@fleetride.local', '+919876543224', 'demo_emp_5'),
  ('00000000-0000-0000-0004-000000000001', 'Ravi Kumar', 'driver', 'driver1@fleetride.local', '+919876543230', 'demo_drv_1'),
  ('00000000-0000-0000-0004-000000000002', 'Suresh Patil', 'driver', 'driver2@fleetride.local', '+919876543231', 'demo_drv_2'),
  ('00000000-0000-0000-0004-000000000003', 'Amit Singh', 'driver', 'driver3@fleetride.local', '+919876543232', 'demo_drv_3'),
  ('00000000-0000-0000-0004-000000000004', 'Priya Sharma', 'driver', 'driver4@fleetride.local', '+919876543233', 'demo_drv_4'),
  ('00000000-0000-0000-0004-000000000005', 'Rajesh Verma', 'driver', 'driver5@fleetride.local', '+919876543234', 'demo_drv_5')
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  role = EXCLUDED.role,
  email = EXCLUDED.email,
  phone = EXCLUDED.phone;

-- 8. Seed Drivers
INSERT INTO drivers (id, profile_id, status, license_no, rating_avg) VALUES
  ('00000000-0000-0000-0005-000000000001', '00000000-0000-0000-0004-000000000001', 'available', 'DL-KA-01-2019-001', 4.8),
  ('00000000-0000-0000-0005-000000000002', '00000000-0000-0000-0004-000000000002', 'available', 'DL-KA-01-2020-002', 4.9),
  ('00000000-0000-0000-0005-000000000003', '00000000-0000-0000-0004-000000000003', 'available', 'DL-KA-01-2021-003', 4.7),
  ('00000000-0000-0000-0005-000000000004', '00000000-0000-0000-0004-000000000004', 'available', 'DL-KA-01-2022-004', 4.6),
  ('00000000-0000-0000-0005-000000000005', '00000000-0000-0000-0004-000000000005', 'available', 'DL-KA-01-2023-005', 4.9)
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  license_no = EXCLUDED.license_no,
  rating_avg = EXCLUDED.rating_avg;

-- 9. Grant Permissions for Supabase API Roles
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
