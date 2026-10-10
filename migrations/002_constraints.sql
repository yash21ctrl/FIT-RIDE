-- 002_constraints.sql: GiST Exclusion Constraints for zero double-booking guarantee
-- Uses the blocked_until column (start_time to end_time + buffer) to prevent overlaps

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
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

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
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;
