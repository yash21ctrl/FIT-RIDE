-- 003_seed.sql: Seed data for FleetRide (Team KNIGHT | PS 40)
-- 6 Vehicles, App Config, Seed Users, Drivers, and Starter Bookings

-- 1. App Configuration
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

-- 2. Fleet Vehicles
INSERT INTO vehicles (id, name, type, capacity, status, maintenance_until, odometer_km) VALUES
  ('00000000-0000-0000-0001-000000000001', 'Maruti Swift', 'car', 4, 'available', NULL, 12500),
  ('00000000-0000-0000-0001-000000000002', 'Honda City', 'car', 4, 'available', NULL, 28400),
  ('00000000-0000-0000-0001-000000000003', 'Maruti Ertiga', 'van', 7, 'available', NULL, 45200),
  ('00000000-0000-0000-0001-000000000004', 'Toyota Innova Crysta', 'van', 7, 'available', NULL, 61000),
  ('00000000-0000-0000-0001-000000000005', 'Mahindra Bolero', 'van', 7, 'available', NULL, 78300),
  ('00000000-0000-0000-0001-000000000006', 'Force Tempo Traveller', 'minibus', 12, 'available', NULL, 94000)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  type = EXCLUDED.type,
  capacity = EXCLUDED.capacity,
  status = EXCLUDED.status,
  odometer_km = EXCLUDED.odometer_km;

-- 3. Seed Users in auth.users (if running against Supabase Postgres directly)
DO $$
BEGIN
  -- Insert into auth.users if auth schema exists
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users') THEN
    INSERT INTO auth.users (id, instance_id, aud, role, email, encrypted_password, email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
    VALUES
      -- Managers
      ('00000000-0000-0000-0002-000000000001', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'manager1@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Yashwanth M"}', now(), now()),
      ('00000000-0000-0000-0002-000000000002', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'manager2@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Kavana"}', now(), now()),
      -- Employees
      ('00000000-0000-0000-0003-000000000001', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'emp1@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Ananya Roy"}', now(), now()),
      ('00000000-0000-0000-0003-000000000002', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'emp2@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Vikram Das"}', now(), now()),
      ('00000000-0000-0000-0003-000000000003', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'emp3@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Neha Nair"}', now(), now()),
      ('00000000-0000-0000-0003-000000000004', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'emp4@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Rahul Mehra"}', now(), now()),
      ('00000000-0000-0000-0003-000000000005', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'emp5@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Sneha Patel"}', now(), now()),
      -- Drivers
      ('00000000-0000-0000-0004-000000000001', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'driver1@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Ravi Kumar"}', now(), now()),
      ('00000000-0000-0000-0004-000000000002', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'driver2@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Suresh Patil"}', now(), now()),
      ('00000000-0000-0000-0004-000000000003', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'driver3@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Amit Singh"}', now(), now()),
      ('00000000-0000-0000-0004-000000000004', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'driver4@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Priya Sharma"}', now(), now()),
      ('00000000-0000-0000-0004-000000000005', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', 'driver5@fleetride.local', crypt('Password@123', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}', '{"name":"Rajesh Verma"}', now(), now())
    ON CONFLICT (id) DO NOTHING;
  END IF;
END $$;

-- 4. Profiles
INSERT INTO profiles (id, name, role, phone, telegram_chat_id) VALUES
  ('00000000-0000-0000-0002-000000000001', 'Yashwanth M', 'manager', '+919876543210', 'demo_mgr_1'),
  ('00000000-0000-0000-0002-000000000002', 'Kavana', 'manager', '+919876543211', 'demo_mgr_2'),
  ('00000000-0000-0000-0003-000000000001', 'Ananya Roy', 'employee', '+919876543220', 'demo_emp_1'),
  ('00000000-0000-0000-0003-000000000002', 'Vikram Das', 'employee', '+919876543221', 'demo_emp_2'),
  ('00000000-0000-0000-0003-000000000003', 'Neha Nair', 'employee', '+919876543222', 'demo_emp_3'),
  ('00000000-0000-0000-0003-000000000004', 'Rahul Mehra', 'employee', '+919876543223', 'demo_emp_4'),
  ('00000000-0000-0000-0003-000000000005', 'Sneha Patel', 'employee', '+919876543224', 'demo_emp_5'),
  ('00000000-0000-0000-0004-000000000001', 'Ravi Kumar', 'driver', '+919876543230', 'demo_drv_1'),
  ('00000000-0000-0000-0004-000000000002', 'Suresh Patil', 'driver', '+919876543231', 'demo_drv_2'),
  ('00000000-0000-0000-0004-000000000003', 'Amit Singh', 'driver', '+919876543232', 'demo_drv_3'),
  ('00000000-0000-0000-0004-000000000004', 'Priya Sharma', 'driver', '+919876543233', 'demo_drv_4'),
  ('00000000-0000-0000-0004-000000000005', 'Rajesh Verma', 'driver', '+919876543234', 'demo_drv_5')
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  role = EXCLUDED.role,
  phone = EXCLUDED.phone;

-- 5. Drivers
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

-- 6. Starter Bookings (Demonstrating rest gap, fairness, and low priority bump candidates)

-- Driver 1 (Ravi Kumar): Finished trip 20 minutes ago -> triggers rest-gap rejection (only 20 min rest < 45 min)
INSERT INTO bookings (
  id, employee_id, vehicle_id, driver_id, start_time, end_time, blocked_until, destination, passengers, reason, type, priority, status, created_at
) VALUES (
  '00000000-0000-0000-0006-000000000001',
  '00000000-0000-0000-0003-000000000001',
  '00000000-0000-0000-0001-000000000001',
  '00000000-0000-0000-0005-000000000001',
  now() - interval '2 hours 20 minutes',
  now() - interval '20 minutes',
  now() - interval '5 minutes',
  'Bengaluru Tech Park',
  3,
  'Client meeting',
  'scheduled',
  'normal',
  'COMPLETED',
  now() - interval '3 hours'
) ON CONFLICT (id) DO NOTHING;

-- Driver 2 (Suresh Patil): Has 3 completed trips today -> fairness demo favors drivers with fewer trips
INSERT INTO bookings (
  id, employee_id, vehicle_id, driver_id, start_time, end_time, blocked_until, destination, passengers, reason, type, priority, status, created_at
) VALUES
  ('00000000-0000-0000-0006-000000000002', '00000000-0000-0000-0003-000000000002', '00000000-0000-0000-0001-000000000002', '00000000-0000-0000-0005-000000000002', now() - interval '6 hours', now() - interval '5 hours', now() - interval '4 hours 45 minutes', 'Airport pickup', 2, 'Executive travel', 'scheduled', 'normal', 'COMPLETED', now() - interval '7 hours'),
  ('00000000-0000-0000-0006-000000000003', '00000000-0000-0000-0003-000000000003', '00000000-0000-0000-0001-000000000002', '00000000-0000-0000-0005-000000000002', now() - interval '4 hours', now() - interval '3 hours', now() - interval '2 hours 45 minutes', 'City Center', 3, 'Document delivery', 'scheduled', 'normal', 'COMPLETED', now() - interval '5 hours'),
  ('00000000-0000-0000-0006-000000000004', '00000000-0000-0000-0003-000000000004', '00000000-0000-0000-0001-000000000002', '00000000-0000-0000-0005-000000000002', now() - interval '2 hours', now() - interval '1 hour', now() - interval '45 minutes', 'Electronic City', 2, 'Vendor review', 'scheduled', 'normal', 'COMPLETED', now() - interval '3 hours')
ON CONFLICT (id) DO NOTHING;

-- Future Bookings with mixed priorities (including 2 low-priority for emergency bump demo)
INSERT INTO bookings (
  id, employee_id, vehicle_id, driver_id, start_time, end_time, blocked_until, destination, passengers, reason, type, priority, status, was_bumped, created_at
) VALUES
  -- Future low-priority on Swift with Driver 3 (Amit Singh)
  ('00000000-0000-0000-0006-000000000005', '00000000-0000-0000-0003-000000000001', '00000000-0000-0000-0001-000000000001', '00000000-0000-0000-0005-000000000003', now() + interval '2 hours', now() + interval '4 hours', now() + interval '4 hours 15 minutes', 'Whitefield Office', 3, 'Routine team transfer', 'scheduled', 'low', 'APPROVED', false, now() - interval '30 minutes'),
  -- Future low-priority on Ertiga with Driver 4 (Priya Sharma)
  ('00000000-0000-0000-0006-000000000006', '00000000-0000-0000-0003-000000000002', '00000000-0000-0000-0001-000000000003', '00000000-0000-0000-0005-000000000004', now() + interval '3 hours', now() + interval '6 hours', now() + interval '6 hours 15 minutes', 'Outer Ring Road', 5, 'Supply transport', 'scheduled', 'low', 'CONFIRMED', false, now() - interval '20 minutes'),
  -- Future normal priority on Innova with Driver 5 (Rajesh Verma)
  ('00000000-0000-0000-0006-000000000007', '00000000-0000-0000-0003-000000000003', '00000000-0000-0000-0001-000000000004', '00000000-0000-0000-0005-000000000005', now() + interval '1 day', now() + interval '1 day 4 hours', now() + interval '1 day 4 hours 15 minutes', 'Mysore Client Visit', 6, 'Annual review discussion', 'scheduled', 'normal', 'CONFIRMED', false, now() - interval '10 minutes')
ON CONFLICT (id) DO NOTHING;
