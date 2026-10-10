-- 001_schema.sql: Initial types and schema for FleetRide
-- Enables extensions and creates base domain tables

CREATE EXTENSION IF NOT EXISTS btree_gist;

DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('employee', 'driver', 'manager');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE vehicle_status AS ENUM ('available', 'maintenance', 'retired');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE driver_status AS ENUM ('off', 'available', 'on_trip', 'break');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE booking_type AS ENUM ('scheduled', 'emergency');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE booking_priority AS ENUM ('low', 'normal', 'high', 'emergency');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE booking_status AS ENUM (
    'PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED',
    'IN_PROGRESS', 'COMPLETED', 'REJECTED', 'CANCELLED', 'BUMPED', 'WAITLISTED'
  );
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

-- Profiles: References auth.users
CREATE TABLE IF NOT EXISTS profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name text NOT NULL,
  role user_role NOT NULL,
  phone text,
  telegram_chat_id text
);

-- Vehicles table
CREATE TABLE IF NOT EXISTS vehicles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  type text NOT NULL, -- car, van, minibus
  capacity int NOT NULL CHECK (capacity > 0),
  status vehicle_status NOT NULL DEFAULT 'available',
  maintenance_until timestamptz,
  odometer_km numeric DEFAULT 0
);

-- Drivers table
CREATE TABLE IF NOT EXISTS drivers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  status driver_status NOT NULL DEFAULT 'available',
  license_no text,
  rating_avg numeric DEFAULT 0
);

-- Bookings table
CREATE TABLE IF NOT EXISTS bookings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id uuid NOT NULL REFERENCES profiles(id),
  vehicle_id uuid REFERENCES vehicles(id),
  driver_id uuid REFERENCES drivers(id),
  start_time timestamptz NOT NULL,
  end_time timestamptz NOT NULL,
  blocked_until timestamptz NOT NULL, -- end_time + buffer
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

-- Driver response logs
CREATE TABLE IF NOT EXISTS driver_responses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  driver_id uuid NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
  response text NOT NULL CHECK (response IN ('accepted', 'rejected', 'timeout')),
  reject_reason text CHECK (reject_reason IN ('tired', 'vehicle_issue', 'personal', 'too_far', 'unsafe', 'other')),
  responded_at timestamptz NOT NULL DEFAULT now()
);

-- Decision audit log
CREATE TABLE IF NOT EXISTS decision_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id uuid REFERENCES bookings(id) ON DELETE CASCADE,
  actor_id uuid REFERENCES profiles(id),
  action text NOT NULL, -- approved, overridden, rejected, bumped, auto_approved, exception
  note text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Trips execution
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

-- Live telemetry breadcrumbs
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
