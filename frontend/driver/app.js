// FleetRide Driver PWA Application Logic
let currentDriverProfile = null;
let currentDriverRecord = null;
let assignedRequests = [];
let activeTripBooking = null;
let rejectingBookingId = null;
let countdownInterval = null;
let pollerInterval = null;
let deferredInstallPrompt = null;

// PWA Service Worker Registration & Install Prompt
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/driver/sw.js').then((reg) => {
      console.log('Driver ServiceWorker registered:', reg.scope);
    }).catch((err) => {
      console.warn('Driver ServiceWorker registration failed:', err);
    });
  });
}

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
  const banner = document.getElementById('pwa-install-banner');
  if (banner) banner.style.display = 'flex';
});

document.addEventListener('DOMContentLoaded', () => {
  const installBtn = document.getElementById('pwa-install-btn');
  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (deferredInstallPrompt) {
        deferredInstallPrompt.prompt();
        const { outcome } = await deferredInstallPrompt.userChoice;
        console.log('User install choice:', outcome);
        deferredInstallPrompt = null;
        document.getElementById('pwa-install-banner').style.display = 'none';
      }
    });
  }

  // Check existing session
  checkDriverAuth();
});

// Sound chime synthesizer via Web Audio API
function playAlertChime() {
  try {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
    osc.frequency.setValueAtTime(880.00, audioCtx.currentTime + 0.15); // A5
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.4);
  } catch (e) {
    console.log('Audio chime not permitted without user interaction');
  }

  // Vibration on mobile
  if (navigator.vibrate) {
    navigator.vibrate([200, 100, 200]);
  }
}

// Authentication Check
async function checkDriverAuth() {
  const token = localStorage.getItem('fleet_token');
  if (!token) {
    showDriverLogin();
    return;
  }

  try {
    const res = await api.get('/api/me');
    if (res && res.profile) {
      if (res.profile.role !== 'driver') {
        alert('Access denied: You must be logged in as a driver.');
        api.clearToken();
        showDriverLogin();
        return;
      }
      currentDriverProfile = res.profile;
      showDriverApp();
      loadDriverDashboard();
    } else {
      showDriverLogin();
    }
  } catch (err) {
    console.warn('Auth check error:', err);
    showDriverLogin();
  }
}

function showDriverLogin() {
  document.getElementById('driver-login-view').style.display = 'block';
  document.getElementById('driver-app-view').style.display = 'none';
  if (countdownInterval) clearInterval(countdownInterval);
  if (pollerInterval) clearInterval(pollerInterval);
}

function showDriverApp() {
  document.getElementById('driver-login-view').style.display = 'none';
  document.getElementById('driver-app-view').style.display = 'flex';
  document.getElementById('driver-name-display').textContent = currentDriverProfile.name;
}

// Quick Login
async function quickLoginDriver(identifier) {
  try {
    const res = await api.login(identifier, '123');
    if (res.role !== 'driver') {
      alert('Selected account is not a driver.');
      return;
    }
    currentDriverProfile = res.profile;
    showDriverApp();
    loadDriverDashboard();
  } catch (err) {
    alert(err.message || 'Login failed');
  }
}

async function handleDriverManualLogin(event) {
  if (event) event.preventDefault();
  const idInput = document.getElementById('driver-login-id').value.trim();
  const passInput = document.getElementById('driver-login-password').value.trim() || '123';
  const btn = document.getElementById('driver-login-submit-btn');

  if (!idInput) {
    alert('Please enter your Driver ID (e.g. driver1)');
    return;
  }

  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Logging In...';
    }
    const res = await api.login(idInput, passInput);
    if (res.role !== 'driver') {
      alert('Selected account is not a driver.');
      return;
    }
    currentDriverProfile = res.profile;
    showDriverApp();
    loadDriverDashboard();
  } catch (err) {
    alert(err.message || 'Login failed');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Sign In to Driver App';
    }
  }
}

function handleDriverLogout() {
  api.clearToken();
  currentDriverProfile = null;
  currentDriverRecord = null;
  assignedRequests = [];
  activeTripBooking = null;
  showDriverLogin();
}

// Tab Switching
function switchDriverTab(tabName) {
  ['requests', 'active', 'schedule'].forEach(tab => {
    const el = document.getElementById(`tab-${tab}`);
    const btn = document.getElementById(`nav-btn-${tab}`);
    if (el) el.style.display = (tab === tabName) ? 'block' : 'none';
    if (btn) {
      if (tab === tabName) btn.classList.add('active');
      else btn.classList.remove('active');
    }
  });

  if (tabName === 'active') {
    renderActiveTripView();
  } else if (tabName === 'schedule') {
    renderScheduleView();
  }
}

// Load Dashboard Data
async function loadDriverDashboard() {
  await Promise.all([
    refreshDriverRequests(),
    loadDriverDutyStatus()
  ]);

  // Start polling every 5 seconds for incoming requests
  if (pollerInterval) clearInterval(pollerInterval);
  pollerInterval = setInterval(refreshDriverRequests, 5000);

  // Start countdown timer ticker
  if (countdownInterval) clearInterval(countdownInterval);
  countdownInterval = setInterval(updateCountdowns, 1000);
}

// Duty & Driver Profile details
async function loadDriverDutyStatus() {
  try {
    const driversRes = await api.get('/api/drivers');
    const driversList = driversRes.drivers || [];
    currentDriverRecord = driversList.find(d => d.profile_id === currentDriverProfile.id);

    if (currentDriverRecord) {
      const badge = document.getElementById('driver-status-badge');
      const st = (currentDriverRecord.status || 'available').toLowerCase();
      badge.textContent = st.replace('_', ' ').toUpperCase();
      badge.className = `driver-status-badge status-${st}`;

      document.getElementById('metric-rating').textContent = `★ ${Number(currentDriverRecord.rating_avg || 5.0).toFixed(1)}`;
    }
  } catch (err) {
    console.warn('Could not load driver duty info:', err);
  }
}

// Fetch Incoming Requests
async function refreshDriverRequests() {
  try {
    const res = await api.get('/api/driver/requests');
    const newRequests = res.requests || [];

    // Check if new request arrived to sound chime
    if (newRequests.length > assignedRequests.length) {
      playAlertChime();
    }

    assignedRequests = newRequests;
    renderRequestsList();

    // Check for any currently active or confirmed trip
    await checkForActiveTrip();

  } catch (err) {
    console.warn('Error fetching requests:', err);
  }
}

// Check for active or confirmed trips
async function checkForActiveTrip() {
  try {
    const bookingsRes = await api.get('/api/bookings/mine');
    const allBookings = bookingsRes.bookings || [];

    // Check if there is an in_progress or confirmed booking
    const active = allBookings.find(b => b.status === 'IN_PROGRESS');
    const confirmed = allBookings.find(b => b.status === 'CONFIRMED');

    activeTripBooking = active || confirmed || null;

    const navActiveBtn = document.getElementById('nav-btn-active');
    if (activeTripBooking) {
      navActiveBtn.innerHTML = `
        <span style="font-size: 1.3rem;">🚗</span>
        <span style="color:#10b981; font-weight:bold;">Trip Live!</span>
      `;
    } else {
      navActiveBtn.innerHTML = `
        <span style="font-size: 1.3rem;">🚗</span>
        <span>Active Trip</span>
      `;
    }

    // Update Hours driven today
    computeHoursDrivenToday(allBookings);

  } catch (e) {
    console.warn('Error checking active trips:', e);
  }
}

function computeHoursDrivenToday(bookings) {
  const completedToday = bookings.filter(b => b.status === 'COMPLETED');
  let totalHours = 0;
  completedToday.forEach(b => {
    const s = new Date(b.start_time).getTime();
    const e = new Date(b.end_time).getTime();
    totalHours += Math.max(0, (e - s) / 3600000);
  });

  const hoursEl = document.getElementById('metric-hours-today');
  if (hoursEl) {
    hoursEl.textContent = `${totalHours.toFixed(1)} / 9.0h`;
  }
}

// Render Requests List
function renderRequestsList() {
  const container = document.getElementById('requests-list-container');
  const badge = document.getElementById('requests-count-badge');

  if (assignedRequests.length === 0) {
    badge.style.display = 'none';
    container.innerHTML = `
      <div class="touch-card" style="text-align: center; padding: 2.5rem 1rem;">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">✨</div>
        <h3 style="color: #f1f5f9; margin-bottom: 0.25rem;">No Pending Trips</h3>
        <p style="color: #94a3b8; font-size: 0.9rem; margin: 0;">You're ready for new dispatches. Incoming requests will alert you immediately.</p>
      </div>
    `;
    return;
  }

  badge.style.display = 'inline-block';
  badge.textContent = assignedRequests.length;

  container.innerHTML = assignedRequests.map(req => {
    const isEmergency = req.type === 'emergency' || req.priority === 'emergency';
    return `
      <div class="touch-card" style="${isEmergency ? 'border: 2px solid #ef4444; background: rgba(239, 68, 68, 0.05);' : ''}">
        ${isEmergency ? '<div style="color: #ef4444; font-weight: bold; font-size: 0.85rem; margin-bottom: 0.5rem;">🚨 EMERGENCY PRIORITY DISPATCH</div>' : ''}
        
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.75rem;">
          <div>
            <div style="font-size: 1.15rem; font-weight: 800; color: #f8fafc;">${req.destination}</div>
            <div style="font-size: 0.85rem; color: #94a3b8;">${req.passengers} Passengers · ${req.vehicle_name || 'Assigned Vehicle'}</div>
          </div>
          <div class="countdown-timer" data-respond-by="${req.respond_by || ''}">
            --:--
          </div>
        </div>

        <div style="background: #1e293b; padding: 0.75rem; border-radius: 10px; margin-bottom: 1rem; font-size: 0.85rem; color: #cbd5e1;">
          <div><strong>Schedule:</strong> ${FleetTime.formatIsoLocal(req.start_time)} to ${FleetTime.formatIsoLocal(req.end_time)}</div>
          <div><strong>Purpose:</strong> ${req.reason}</div>
        </div>

        <div style="display: flex; gap: 0.75rem;">
          <button class="btn btn-big btn-reject" style="flex: 1;" onclick="openRejectModal('${req.id}')">
            ✕ Reject
          </button>
          <button class="btn btn-big btn-accept" style="flex: 2;" onclick="acceptTripRequest('${req.id}')">
            ✓ Accept Trip
          </button>
        </div>
      </div>
    `;
  }).join('');

  updateCountdowns();
}

// Countdown Timers
function updateCountdowns() {
  const timerEls = document.querySelectorAll('.countdown-timer');
  const now = Date.now();

  timerEls.forEach(el => {
    const respondByStr = el.getAttribute('data-respond-by');
    if (!respondByStr) {
      el.textContent = 'Active';
      return;
    }

    const target = new Date(respondByStr).getTime();
    const diff = target - now;

    if (diff <= 0) {
      el.textContent = 'EXPIRED';
      el.style.color = '#ef4444';
      el.style.borderColor = '#ef4444';
    } else {
      const minutes = Math.floor(diff / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      el.textContent = `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
    }
  });
}

// Accept Trip
async function acceptTripRequest(bookingId) {
  try {
    await api.post(`/api/driver/bookings/${bookingId}/accept`);
    alert('Trip accepted! Status is now CONFIRMED.');
    await refreshDriverRequests();
    switchDriverTab('active');
  } catch (err) {
    alert(err.message || 'Failed to accept trip');
  }
}

// Reject Trip Modal
function openRejectModal(bookingId) {
  rejectingBookingId = bookingId;
  document.getElementById('reject-modal').style.display = 'flex';
}

function closeRejectModal() {
  rejectingBookingId = null;
  document.getElementById('reject-modal').style.display = 'none';
}

async function submitRejectReason() {
  if (!rejectingBookingId) return;

  const reasonSelect = document.getElementById('reject-reason-select');
  const reason = reasonSelect.value;

  try {
    await api.post(`/api/driver/bookings/${rejectingBookingId}/reject`, {
      reject_reason: reason
    });
    closeRejectModal();
    alert('Trip rejected. Reassignment workflow initiated.');
    await refreshDriverRequests();
    await loadDriverDutyStatus();
  } catch (err) {
    alert(err.message || 'Failed to reject trip');
  }
}

// Render Active Trip View
function renderActiveTripView() {
  const container = document.getElementById('active-trip-container');

  if (!activeTripBooking) {
    container.innerHTML = `
      <div class="touch-card" style="text-align: center; padding: 2.5rem 1rem;">
        <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🅿️</div>
        <h3 style="color: #f1f5f9; margin-bottom: 0.25rem;">No Active Trip</h3>
        <p style="color: #94a3b8; font-size: 0.9rem; margin: 0;">Accept an incoming trip request to begin checklist and start odometer logging.</p>
      </div>
    `;
    return;
  }

  const b = activeTripBooking;
  const isConfirmed = b.status === 'CONFIRMED';
  const isInProgress = b.status === 'IN_PROGRESS';

  if (isConfirmed) {
    container.innerHTML = `
      <div class="touch-card" style="border: 2px solid #38bdf8;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <span style="font-size: 0.8rem; font-weight: bold; color: #38bdf8; text-transform: uppercase;">STEP 1: PRE-TRIP CHECKLIST</span>
          <span class="driver-status-badge status-available">CONFIRMED</span>
        </div>

        <h3 style="font-size: 1.3rem; margin: 0 0 0.5rem; color: #f8fafc;">${b.destination}</h3>
        <p style="color: #94a3b8; font-size: 0.85rem; margin-bottom: 1.25rem;">
          Vehicle: <strong>${b.vehicle_name || 'Fleet Vehicle'}</strong> · ${b.passengers} Passengers
        </p>

        <!-- Checklist -->
        <div style="background: #1e293b; padding: 1rem; border-radius: 12px; margin-bottom: 1.25rem;">
          <div style="font-weight: 700; font-size: 0.9rem; color: #f8fafc; margin-bottom: 0.75rem;">Vehicle Inspection Checklist</div>
          <div style="display: flex; flex-direction: column; gap: 0.6rem; font-size: 0.9rem; color: #cbd5e1;">
            <label style="display: flex; align-items: center; gap: 0.6rem; cursor: pointer;">
              <input type="checkbox" id="chk-tires" checked style="width: 18px; height: 18px;">
              <span>Tire pressure &amp; condition checked</span>
            </label>
            <label style="display: flex; align-items: center; gap: 0.6rem; cursor: pointer;">
              <input type="checkbox" id="chk-fuel" checked style="width: 18px; height: 18px;">
              <span>Fuel / battery level adequate</span>
            </label>
            <label style="display: flex; align-items: center; gap: 0.6rem; cursor: pointer;">
              <input type="checkbox" id="chk-mirrors" checked style="width: 18px; height: 18px;">
              <span>Mirrors and lights operational</span>
            </label>
            <label style="display: flex; align-items: center; gap: 0.6rem; cursor: pointer;">
              <input type="checkbox" id="chk-clean" checked style="width: 18px; height: 18px;">
              <span>Cabin cleaned and sanitized</span>
            </label>
          </div>
        </div>

        <!-- Starting Odometer Input -->
        <div style="margin-bottom: 1.5rem;">
          <label style="display: block; font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.4rem;">
            Starting Odometer Reading (KM)
          </label>
          <input type="number" id="start-odometer-input" value="12500" style="width: 100%; font-size: 1.25rem; font-weight: bold; background: #1e293b; color: white; border: 1px solid #334155; padding: 0.75rem 1rem; border-radius: 10px;">
        </div>

        <button class="btn btn-big btn-start" onclick="handleStartTrip('${b.id}')">
          🚀 Start Trip (Begin Driving)
        </button>
      </div>
    `;
  } else if (isInProgress) {
    container.innerHTML = `
      <div class="touch-card" style="border: 2px solid #10b981;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <span style="font-size: 0.8rem; font-weight: bold; color: #10b981; text-transform: uppercase;">STEP 2: TRIP IN PROGRESS</span>
          <span class="driver-status-badge status-on_trip">ON TRIP</span>
        </div>

        <h3 style="font-size: 1.3rem; margin: 0 0 0.5rem; color: #f8fafc;">${b.destination}</h3>
        <p style="color: #94a3b8; font-size: 0.85rem; margin-bottom: 1.25rem;">
          Vehicle: <strong>${b.vehicle_name || 'Fleet Vehicle'}</strong> · Telemetry active
        </p>

        <!-- Live Telemetry Card -->
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); padding: 1rem; border-radius: 12px; margin-bottom: 1.25rem;">
          <div style="color: #10b981; font-weight: bold; font-size: 0.95rem;">● Live Location Broadcasting</div>
          <div style="font-size: 0.8rem; color: #94a3b8; margin-top: 0.25rem;">Trip telemetry is being synchronized with employee and manager dashboards.</div>
        </div>

        <!-- End Odometer and Fuel Input -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 1.5rem;">
          <div>
            <label style="display: block; font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.4rem;">End Odometer (KM)</label>
            <input type="number" id="end-odometer-input" value="12545" style="width: 100%; font-size: 1.15rem; font-weight: bold; background: #1e293b; color: white; border: 1px solid #334155; padding: 0.75rem; border-radius: 10px;">
          </div>
          <div>
            <label style="display: block; font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.4rem;">Fuel Added (L)</label>
            <input type="number" id="fuel-added-input" value="0" style="width: 100%; font-size: 1.15rem; font-weight: bold; background: #1e293b; color: white; border: 1px solid #334155; padding: 0.75rem; border-radius: 10px;">
          </div>
        </div>

        <button class="btn btn-big btn-end" onclick="handleEndTrip('${b.id}')">
          🏁 Complete &amp; End Trip
        </button>
      </div>
    `;
  }
}

// Start Trip Action
async function handleStartTrip(bookingId) {
  const odoInput = document.getElementById('start-odometer-input');
  const startOdometer = parseFloat(odoInput.value) || 0;

  const checklist = {
    tires: document.getElementById('chk-tires').checked,
    fuel: document.getElementById('chk-fuel').checked,
    mirrors: document.getElementById('chk-mirrors').checked,
    clean: document.getElementById('chk-clean').checked
  };

  try {
    await api.post(`/api/trips/${bookingId}/start`, {
      start_odometer: startOdometer,
      checklist: checklist
    });
    alert('Trip marked IN_PROGRESS! Driver status updated to ON_TRIP.');
    await refreshDriverRequests();
    renderActiveTripView();
    await loadDriverDutyStatus();
  } catch (err) {
    alert(err.message || 'Failed to start trip');
  }
}

// End Trip Action
async function handleEndTrip(bookingId) {
  const endOdo = parseFloat(document.getElementById('end-odometer-input').value) || 0;
  const fuel = parseFloat(document.getElementById('fuel-added-input').value) || 0;

  try {
    await api.post(`/api/trips/${bookingId}/end`, {
      end_odometer: endOdo,
      fuel_added: fuel
    });
    alert('Trip COMPLETED! Vehicle and driver are now freed to AVAILABLE.');
    activeTripBooking = null;
    await refreshDriverRequests();
    renderActiveTripView();
    await loadDriverDutyStatus();
  } catch (err) {
    alert(err.message || 'Failed to end trip');
  }
}

// Schedule View
async function renderScheduleView() {
  const container = document.getElementById('schedule-list-container');
  try {
    const res = await api.get('/api/bookings/mine');
    const trips = res.bookings || [];

    if (trips.length === 0) {
      container.innerHTML = '<p style="color: #94a3b8; font-size: 0.9rem;">No scheduled trips recorded.</p>';
      return;
    }

    container.innerHTML = trips.map(t => `
      <div style="background: #1e293b; padding: 0.8rem; border-radius: 10px; margin-bottom: 0.6rem; border-left: 4px solid #38bdf8;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong style="color: #f8fafc; font-size: 0.95rem;">${t.destination}</strong>
          <span style="font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 9999px; background: rgba(56, 189, 248, 0.15); color: #38bdf8;">${t.status}</span>
        </div>
        <div style="font-size: 0.8rem; color: #94a3b8; margin-top: 0.3rem;">
          ${FleetTime.formatIsoLocal(t.start_time)}
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<p style="color: #ef4444;">Error loading schedule.</p>';
  }
}
