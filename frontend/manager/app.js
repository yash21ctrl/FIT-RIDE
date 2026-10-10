// Fleet Operations Manager Portal Application Logic
let currentManagerProfile = null;
let currentGanttMode = 'vehicles'; // 'vehicles' | 'drivers'
let allVehicles = [];
let allDrivers = [];
let pendingQueue = [];
let overridingBookingId = null;
let rejectingBookingId = null;

document.addEventListener('DOMContentLoaded', () => {
  checkManagerAuth();
});

// Authentication
async function checkManagerAuth() {
  const token = localStorage.getItem('fleet_token');
  if (!token) {
    showManagerLogin();
    return;
  }

  try {
    const res = await api.get('/api/me');
    if (res && res.profile) {
      if (res.profile.role !== 'manager') {
        alert('Access denied: You must be logged in as a Manager.');
        api.clearToken();
        showManagerLogin();
        return;
      }
      currentManagerProfile = res.profile;
      showManagerApp();
      loadInitialData();
    } else {
      showManagerLogin();
    }
  } catch (err) {
    console.warn('Auth check error:', err);
    showManagerLogin();
  }
}

function showManagerLogin() {
  document.getElementById('manager-login-view').style.display = 'block';
  document.getElementById('manager-app-view').style.display = 'none';
}

function showManagerApp() {
  document.getElementById('manager-login-view').style.display = 'none';
  document.getElementById('manager-app-view').style.display = 'block';
  document.getElementById('manager-name-display').textContent = currentManagerProfile.name;
}

async function quickLoginManager(email) {
  try {
    const res = await api.login(email, 'Password@123');
    if (res.role !== 'manager') {
      alert('Selected account is not a manager.');
      return;
    }
    currentManagerProfile = res.profile;
    showManagerApp();
    loadInitialData();
  } catch (err) {
    alert(err.message || 'Login failed');
  }
}

function handleManagerLogout() {
  api.clearToken();
  currentManagerProfile = null;
  showManagerLogin();
}

// Initial Data Load
async function loadInitialData() {
  await Promise.all([
    loadApprovalQueue(),
    loadFleetData(),
    loadAlertsData()
  ]);
}

// Navigation Tabs
function switchManagerTab(tab) {
  const tabs = ['queue', 'gantt', 'fleet', 'analytics', 'history', 'alerts'];
  tabs.forEach(t => {
    const viewEl = document.getElementById(`view-${t}`);
    const btnEl = document.getElementById(`mgr-tab-${t}`);
    if (viewEl) viewEl.style.display = (t === tab) ? 'block' : 'none';
    if (btnEl) {
      if (t === tab) btnEl.classList.add('active');
      else btnEl.classList.remove('active');
    }
  });

  if (tab === 'queue') loadApprovalQueue();
  else if (tab === 'gantt') loadGanttData();
  else if (tab === 'fleet') loadFleetData();
  else if (tab === 'analytics') loadAnalyticsData();
  else if (tab === 'history') loadHistoryData();
  else if (tab === 'alerts') loadAlertsData();
}

// TAB 1: APPROVAL QUEUE
async function loadApprovalQueue() {
  try {
    const res = await api.get('/api/manager/queue');
    pendingQueue = res.queue || [];

    const badge = document.getElementById('queue-badge');
    badge.textContent = pendingQueue.length;
    badge.style.display = pendingQueue.length > 0 ? 'inline-block' : 'none';

    renderApprovalQueue();
  } catch (err) {
    console.warn('Error loading queue:', err);
  }
}

function renderApprovalQueue() {
  const container = document.getElementById('approval-queue-list');
  if (pendingQueue.length === 0) {
    container.innerHTML = `
      <div class="card" style="text-align: center; padding: 3rem 1rem;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🎉</div>
        <h3 style="color: #f8fafc; margin-bottom: 0.25rem;">Approval Queue is Empty</h3>
        <p style="color: #94a3b8; margin: 0;">All routine requests have been approved or automatically dispatched.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = pendingQueue.map(b => {
    const isPending = b.status === 'PENDING';
    const isDriverPending = b.status === 'DRIVER_PENDING';
    const borderColor = isPending ? '#f59e0b' : '#38bdf8';
    const statusBadge = isPending
      ? `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4);">AWAITING APPROVAL</span>`
      : `<span class="badge" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4);">DISPATCHED TO DRIVER</span>`;

    return `
      <div class="card" style="padding: 1.5rem; margin-bottom: 1.25rem; border-left: 4px solid ${borderColor};">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;">
          <div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <h3 style="font-size: 1.25rem; margin: 0; color: #f8fafc;">${b.destination}</h3>
              <span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4);">${b.priority.toUpperCase()}</span>
              ${statusBadge}
            </div>
            <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 0.25rem;">
              Requested by ${b.employee_name || 'Employee'} · ${b.passengers} Passengers · Purpose: "${b.reason}"
            </div>
          </div>
          <div style="text-align: right; font-size: 0.85rem; color: #cbd5e1;">
            <div><strong>Schedule:</strong> ${FleetTime.formatIsoLocal(b.start_time)}</div>
            <div>to ${FleetTime.formatIsoLocal(b.end_time)}</div>
          </div>
        </div>

        <!-- Allocation Engine Explanation Box -->
        <div style="background: #090d16; border: 1px solid #1e293b; border-radius: 12px; padding: 1rem; margin-bottom: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
            <div style="font-size: 0.8rem; font-weight: 700; color: #38bdf8; text-transform: uppercase;">
              ⚙️ Allocation Engine Recommendation
            </div>
            ${b.respond_by ? `<div style="font-size: 0.75rem; color: #f59e0b;">Driver Response Due: ${FleetTime.formatIsoLocal(b.respond_by)}</div>` : ''}
          </div>
          <div style="font-size: 0.95rem; color: #f1f5f9; font-weight: 600; margin-bottom: 0.5rem;">
            Vehicle: <span style="color: #38bdf8;">${b.vehicle_name || 'Assigned Vehicle'}</span> &nbsp;|&nbsp; 
            Driver: <span style="color: #10b981;">${b.driver_name || 'Assigned Driver'}</span>
          </div>
          <div style="font-size: 0.85rem; color: #94a3b8; line-height: 1.5;">
            ${b.decision_reason || 'Selected based on capacity fit and driver rest gap validation.'}
          </div>
        </div>

        <!-- Actions -->
        <div style="display: flex; gap: 0.75rem; justify-content: flex-end;">
          <button class="btn" style="background: #1e293b; color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);" onclick="openMgrRejectModal('${b.id}')">
            ✕ Reject
          </button>
          <button class="btn" style="background: #1e293b; color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.3);" onclick="openOverrideModal('${b.id}')">
            ✎ Override Assignment
          </button>
          ${isPending ? `
            <button class="btn" style="background: #10b981; color: white; font-weight: bold; padding: 0.6rem 1.5rem;" onclick="approveBooking('${b.id}')">
              ✓ Approve Request
            </button>
          ` : `
            <button class="btn" style="background: #0284c7; color: white; font-weight: 600; padding: 0.6rem 1.25rem;" onclick="openOverrideModal('${b.id}')">
              ↻ Re-dispatch
            </button>
          `}
        </div>
      </div>
    `;
  }).join('');
}

// Approve Action
async function approveBooking(bookingId) {
  try {
    await api.post(`/api/manager/bookings/${bookingId}/approve`);
    alert('Booking approved! Dispatched to driver with response window.');
    await loadApprovalQueue();
    await loadAlertsData();
  } catch (err) {
    alert(err.message || 'Approval failed');
  }
}

// Override Modal
function openOverrideModal(bookingId) {
  overridingBookingId = bookingId;
  const vehSelect = document.getElementById('override-vehicle-select');
  const drvSelect = document.getElementById('override-driver-select');

  vehSelect.innerHTML = allVehicles.map(v => `
    <option value="${v.id}">${v.name} (${v.type.toUpperCase()}, ${v.capacity} seats, Status: ${v.status})</option>
  `).join('');

  drvSelect.innerHTML = allDrivers.map(d => `
    <option value="${d.id}">${d.name} (Status: ${d.status}, Rating: ★${d.rating_avg})</option>
  `).join('');

  document.getElementById('override-modal').style.display = 'flex';
}

function closeOverrideModal() {
  overridingBookingId = null;
  document.getElementById('override-modal').style.display = 'none';
}

async function submitOverride() {
  if (!overridingBookingId) return;

  const vehicleId = document.getElementById('override-vehicle-select').value;
  const driverId = document.getElementById('override-driver-select').value;

  try {
    await api.post(`/api/manager/bookings/${overridingBookingId}/override`, {
      vehicle_id: vehicleId,
      driver_id: driverId,
      note: 'Manual vehicle/driver override by manager'
    });
    closeOverrideModal();
    alert('Assignment overridden successfully. Dispatched to new driver.');
    await loadApprovalQueue();
    await loadGanttData();
  } catch (err) {
    alert(`Override Error: ${err.message}`);
  }
}

// Reject Modal
function openMgrRejectModal(bookingId) {
  rejectingBookingId = bookingId;
  document.getElementById('mgr-reject-reason-input').value = '';
  document.getElementById('mgr-reject-modal').style.display = 'flex';
}

function closeMgrRejectModal() {
  rejectingBookingId = null;
  document.getElementById('mgr-reject-modal').style.display = 'none';
}

async function submitMgrReject() {
  if (!rejectingBookingId) return;
  const reason = document.getElementById('mgr-reject-reason-input').value.trim();
  if (!reason) {
    alert('Rejection reason note is required.');
    return;
  }

  try {
    await api.post(`/api/manager/bookings/${rejectingBookingId}/reject`, {
      reason: reason
    });
    closeMgrRejectModal();
    alert('Booking rejected and slot released.');
    await loadApprovalQueue();
    await loadGanttData();
    await loadAlertsData();
  } catch (err) {
    alert(err.message || 'Rejection failed');
  }
}

// TAB 2: CSS GRID GANTT TIMELINE
function toggleGanttView(mode) {
  currentGanttMode = mode;
  document.getElementById('gantt-toggle-veh').style.background = mode === 'vehicles' ? '#38bdf8' : 'transparent';
  document.getElementById('gantt-toggle-veh').style.color = mode === 'vehicles' ? 'black' : '#94a3b8';

  document.getElementById('gantt-toggle-drv').style.background = mode === 'drivers' ? '#38bdf8' : 'transparent';
  document.getElementById('gantt-toggle-drv').style.color = mode === 'drivers' ? 'black' : '#94a3b8';

  loadGanttData();
}

async function loadGanttData() {
  try {
    const res = await api.get('/api/manager/gantt');
    const vehicles = res.vehicles || [];
    const drivers = res.drivers || [];
    const bookings = res.bookings || [];

    allVehicles = vehicles;
    allDrivers = drivers;

    renderGanttChart(vehicles, drivers, bookings);
  } catch (err) {
    console.warn('Error loading Gantt data:', err);
  }
}

function renderGanttChart(vehicles, drivers, bookings) {
  const container = document.getElementById('gantt-rows-container');
  const rows = currentGanttMode === 'vehicles' ? vehicles : drivers;

  if (rows.length === 0) {
    container.innerHTML = '<div style="padding: 2rem; text-align: center; color: #94a3b8;">No resources found.</div>';
    return;
  }

  container.innerHTML = rows.map(r => {
    // Find bookings assigned to this resource
    const rowBookings = bookings.filter(b => {
      if (currentGanttMode === 'vehicles') {
        return b.vehicle_id === r.id && !['CANCELLED', 'REJECTED'].includes(b.status);
      } else {
        return b.driver_id === r.id && !['CANCELLED', 'REJECTED'].includes(b.status);
      }
    });

    // Generate 24 empty background cells
    const cellsHtml = Array.from({ length: 24 }).map(() => '<div class="gantt-grid-cell"></div>').join('');

    // Generate absolutely positioned booking blocks
    const blocksHtml = rowBookings.map(b => {
      const s = new Date(b.start_time);
      const e = new Date(b.end_time);

      // Convert UTC to local IST hour fractions
      const startHourLocal = s.getUTCHours() + (s.getUTCMinutes() / 60) + 5.5; // IST = UTC + 5.5
      const endHourLocal = e.getUTCHours() + (e.getUTCMinutes() / 60) + 5.5;

      const normStart = (startHourLocal % 24);
      let durationHours = (e.getTime() - s.getTime()) / 3600000;
      if (durationHours <= 0) durationHours = 1;

      const leftPct = Math.max(0, Math.min(95, (normStart / 24) * 100));
      const widthPct = Math.max(3, Math.min(100 - leftPct, (durationHours / 24) * 100));

      const statusClass = `block-${b.status.toLowerCase()}`;
      return `
        <div class="gantt-booking-block ${statusClass}" 
             style="left: ${leftPct.toFixed(2)}%; width: ${widthPct.toFixed(2)}%;"
             title="${b.destination} (${b.status})"
             onclick='openGanttDetail(${JSON.stringify(b).replace(/'/g, "&#39;")})'>
          ${b.destination} (${b.passengers}p)
        </div>
      `;
    }).join('');

    return `
      <div class="gantt-row">
        <div class="gantt-label">
          <div style="font-weight: 700; color: #f8fafc;">${r.name}</div>
          <div style="font-size: 0.75rem; color: #94a3b8;">
            ${currentGanttMode === 'vehicles' ? `${r.capacity} seats · ${r.status}` : `★ ${r.rating_avg} · ${r.status}`}
          </div>
        </div>
        <div class="gantt-grid-cells">
          ${cellsHtml}
          ${blocksHtml}
        </div>
      </div>
    `;
  }).join('');
}

function openGanttDetail(b) {
  document.getElementById('gantt-detail-title').textContent = b.destination;
  document.getElementById('gantt-detail-body').innerHTML = `
    <div><strong>Status:</strong> <span class="badge" style="background:#1e293b; color:#38bdf8;">${b.status}</span></div>
    <div><strong>Schedule (IST):</strong> ${FleetTime.formatIsoLocal(b.start_time)} to ${FleetTime.formatIsoLocal(b.end_time)}</div>
    <div><strong>Passengers:</strong> ${b.passengers}</div>
    <div><strong>Vehicle:</strong> ${b.vehicle_name || 'N/A'}</div>
    <div><strong>Driver:</strong> ${b.driver_name || 'N/A'}</div>
    <div><strong>Trip Purpose:</strong> ${b.reason}</div>
    <div style="margin-top: 0.75rem; padding: 0.75rem; background: #0f172a; border-radius: 8px; border: 1px solid #1e293b;">
      <div style="font-size: 0.8rem; color: #38bdf8; font-weight: bold; margin-bottom: 0.25rem;">DECISION LOG / REASON:</div>
      <div style="font-size: 0.85rem; color: #cbd5e1;">${b.decision_reason || 'Standard booking confirmed.'}</div>
    </div>
  `;
  document.getElementById('gantt-detail-modal').style.display = 'flex';
}

function closeGanttDetailModal() {
  document.getElementById('gantt-detail-modal').style.display = 'none';
}

// TAB 3: FLEET & DRIVERS
async function loadFleetData() {
  try {
    const [vRes, dRes] = await Promise.all([
      api.get('/api/vehicles'),
      api.get('/api/drivers')
    ]);

    allVehicles = vRes.vehicles || [];
    allDrivers = dRes.drivers || [];

    renderFleetLists();
  } catch (err) {
    console.warn('Error loading fleet lists:', err);
  }
}

function renderFleetLists() {
  const vContainer = document.getElementById('manager-vehicles-list');
  const dContainer = document.getElementById('manager-drivers-list');

  vContainer.innerHTML = allVehicles.map(v => {
    const isMaint = v.status === 'maintenance';
    return `
      <div class="card" style="padding: 1rem; display: flex; justify-content: space-between; align-items: center; ${isMaint ? 'border-color: #f59e0b;' : ''}">
        <div>
          <div style="font-weight: 700; color: #f8fafc; font-size: 1rem;">${v.name}</div>
          <div style="font-size: 0.8rem; color: #94a3b8;">
            ${v.type.toUpperCase()} · ${v.capacity} Seats · ${v.odometer_km} km
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 0.6rem;">
          <span class="badge ${isMaint ? 'status-break' : 'status-available'}">${v.status.toUpperCase()}</span>
          <button class="btn" style="background: #1e293b; color: ${isMaint ? '#10b981' : '#f59e0b'}; font-size: 0.75rem; padding: 0.35rem 0.6rem;" onclick="toggleVehicleMaintenance('${v.id}', '${v.status}')">
            ${isMaint ? 'Clear Maintenance' : 'Set Maintenance'}
          </button>
        </div>
      </div>
    `;
  }).join('');

  dContainer.innerHTML = allDrivers.map(d => {
    return `
      <div class="card" style="padding: 1rem; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="font-weight: 700; color: #f8fafc; font-size: 1rem;">${d.name}</div>
          <div style="font-size: 0.8rem; color: #94a3b8;">
            License: ${d.license_no || 'N/A'} · Rating: ★ ${d.rating_avg}
          </div>
        </div>
        <span class="badge status-${d.status.toLowerCase()}">${d.status.toUpperCase()}</span>
      </div>
    `;
  }).join('');
}

async function toggleVehicleMaintenance(vehicleId, currentStatus) {
  const newStatus = currentStatus === 'maintenance' ? 'available' : 'maintenance';
  try {
    await api.patch(`/api/vehicles/${vehicleId}`, {
      status: newStatus
    });
    alert(`Vehicle status updated to ${newStatus}.`);
    await loadFleetData();
    await loadGanttData();
  } catch (err) {
    alert(err.message || 'Failed to update vehicle');
  }
}

function openAddVehicleModal() {
  document.getElementById('add-vehicle-modal').style.display = 'flex';
}

function closeAddVehicleModal() {
  document.getElementById('add-vehicle-modal').style.display = 'none';
}

async function submitAddVehicle() {
  const name = document.getElementById('add-veh-name').value.trim();
  const type = document.getElementById('add-veh-type').value;
  const cap = parseInt(document.getElementById('add-veh-cap').value, 10);

  if (!name || isNaN(cap) || cap <= 0) {
    alert('Please enter a valid vehicle name and positive capacity.');
    return;
  }

  try {
    await api.post('/api/vehicles', {
      name: name,
      type: type,
      capacity: cap,
      odometer_km: 0
    });
    closeAddVehicleModal();
    alert('Vehicle added successfully to fleet.');
    await loadFleetData();
    await loadGanttData();
  } catch (err) {
    alert(err.message || 'Failed to add vehicle');
  }
}

// TAB 4: AUDIT HISTORY
async function loadHistoryData() {
  const statusFilter = document.getElementById('history-status-filter').value;
  try {
    const res = await api.get(`/api/manager/history?status=${statusFilter}`);
    const items = res.history || [];
    const tbody = document.getElementById('history-table-body');

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: #94a3b8; padding: 2rem;">No historical bookings found matching filter.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(b => `
      <tr>
        <td style="font-family: monospace; font-size: 0.75rem;">${b.id.substring(0, 8)}...</td>
        <td style="font-weight: 600; color: #f8fafc;">${b.destination}</td>
        <td>${b.vehicle_name || 'Unassigned'} / ${b.driver_name || 'Unassigned'}</td>
        <td style="font-size: 0.8rem;">${FleetTime.formatIsoLocal(b.start_time)}</td>
        <td>${b.passengers}p</td>
        <td><span class="badge status-${b.status.toLowerCase()}">${b.status}</span></td>
        <td style="font-size: 0.8rem; color: #94a3b8;">${b.decision_reason || '-'}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.warn('Error loading history:', err);
  }
}

// TAB 5: ALERTS & WAITLIST
async function loadAlertsData() {
  try {
    const res = await api.get('/api/manager/alerts');
    const emergencies = res.emergencies || [];
    const waitlisted = res.waitlisted || [];
    const bumped = res.bumped || [];

    const badge = document.getElementById('alerts-badge');
    const total = res.total_alerts || 0;
    badge.textContent = total;
    badge.style.display = total > 0 ? 'inline-block' : 'none';

    renderAlertsCards(emergencies, waitlisted, bumped);
  } catch (err) {
    console.warn('Error loading alerts:', err);
  }
}

function renderAlertsCards(emergencies, waitlisted, bumped) {
  const container = document.getElementById('alerts-cards-container');

  if (emergencies.length === 0 && waitlisted.length === 0 && bumped.length === 0) {
    container.innerHTML = `
      <div class="card" style="text-align: center; padding: 3rem 1rem;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🛡️</div>
        <h3 style="color: #f8fafc; margin-bottom: 0.25rem;">Zero Operational Alerts</h3>
        <p style="color: #94a3b8; margin: 0;">No active emergencies or waitlisted bookings pending resolution.</p>
      </div>
    `;
    return;
  }

  let html = '';

  if (emergencies.length > 0) {
    html += '<h3 style="color: #ef4444; margin-top: 0;">🚨 High Priority Emergencies</h3>';
    emergencies.forEach(e => {
      html += `
        <div class="card" style="border: 2px solid #ef4444; background: rgba(239,68,68,0.05); padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between;">
            <div>
              <strong style="color: #f8fafc; font-size: 1.1rem;">${e.destination}</strong>
              <div style="font-size: 0.85rem; color: #94a3b8;">Reason: ${e.reason} · ${e.passengers} Passengers</div>
            </div>
            <span class="badge" style="background:#ef4444; color:white;">EMERGENCY DISPATCH</span>
          </div>
        </div>
      `;
    });
  }

  if (waitlisted.length > 0) {
    html += '<h3 style="color: #f59e0b; margin-top: 1.5rem;">⏳ Waitlisted Requests (Auto-Promotion Enabled)</h3>';
    waitlisted.forEach(w => {
      html += `
        <div class="card" style="border-left: 4px solid #f59e0b; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between;">
            <div>
              <strong style="color: #f8fafc; font-size: 1.1rem;">${w.destination}</strong>
              <div style="font-size: 0.85rem; color: #94a3b8;">${w.passengers} Passengers · Time: ${FleetTime.formatIsoLocal(w.start_time)}</div>
            </div>
            <span class="badge" style="background:#1e293b; color:#f59e0b;">WAITLISTED</span>
          </div>
        </div>
      `;
    });
  }

  if (bumped.length > 0) {
    html += '<h3 style="color: #ea580c; margin-top: 1.5rem;">⚠️ Bumped Bookings (Protected from Second Bump)</h3>';
    bumped.forEach(b => {
      html += `
        <div class="card" style="border-left: 4px solid #ea580c; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between;">
            <div>
              <strong style="color: #f8fafc; font-size: 1.1rem;">${b.destination}</strong>
              <div style="font-size: 0.85rem; color: #94a3b8;">Previously scheduled · Flagged was_bumped = True</div>
            </div>
            <span class="badge" style="background:#1e293b; color:#ea580c;">BUMPED</span>
          </div>
        </div>
      `;
    });
  }

  container.innerHTML = html;
}

// TAB: ANALYTICS & INSIGHTS
async function loadAnalyticsData() {
  try {
    const res = await api.get('/api/manager/analytics');
    
    // KPI metrics
    if (res.summary) {
      document.getElementById('metric-total-vehicles').textContent = res.summary.total_vehicles || 0;
      document.getElementById('metric-total-drivers').textContent = res.summary.total_drivers || 0;
      document.getElementById('metric-total-bookings').textContent = res.summary.total_bookings || 0;
    }
    
    let totalRejects = 0;
    if (res.reject_reasons) {
      totalRejects = Object.values(res.reject_reasons).reduce((a, b) => a + b, 0);
      document.getElementById('metric-total-rejects').textContent = totalRejects;
    }

    // Vehicle table
    const vehBody = document.getElementById('analytics-vehicle-table-body');
    if (vehBody && res.vehicle_utilization) {
      vehBody.innerHTML = res.vehicle_utilization.map(v => `
        <tr>
          <td><strong>${v.name}</strong></td>
          <td><span class="badge" style="background:#1e293b; color:#94a3b8;">${v.type}</span></td>
          <td>${v.capacity} Seats</td>
          <td><span class="badge ${v.status === 'available' ? 'badge-success' : 'badge-warning'}">${v.status}</span></td>
          <td>${v.total_trips}</td>
          <td>${v.total_hours}h</td>
          <td>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <div style="flex: 1; background: #1e293b; height: 8px; border-radius: 4px; overflow: hidden;">
                <div style="background: #38bdf8; width: ${v.utilization_pct}%; height: 100%;"></div>
              </div>
              <span style="font-size: 0.8rem; color: #cbd5e1;">${v.utilization_pct}%</span>
            </div>
          </td>
        </tr>
      `).join('');
    }

    // Driver table
    const drvBody = document.getElementById('analytics-driver-table-body');
    if (drvBody && res.driver_fairness) {
      drvBody.innerHTML = res.driver_fairness.map(d => `
        <tr>
          <td><strong>${d.name}</strong></td>
          <td style="color: #94a3b8;">${d.phone || '—'}</td>
          <td>⭐ ${d.rating_avg.toFixed(1)}</td>
          <td><span class="badge ${d.status === 'available' ? 'badge-success' : 'badge-neutral'}">${d.status}</span></td>
          <td>${d.total_trips}</td>
          <td>${d.total_hours}h</td>
        </tr>
      `).join('');
    }

    // Reject reasons cards
    const rejContainer = document.getElementById('analytics-reject-reasons-cards');
    if (rejContainer && res.reject_reasons) {
      const labels = {
        tired: 'Tired / Fatigue',
        vehicle_issue: 'Vehicle Issue',
        personal: 'Personal / Family',
        too_far: 'Distance / Too Far',
        unsafe: 'Safety / Route',
        timeout: 'Response Timeout',
        other: 'Other'
      };
      rejContainer.innerHTML = Object.entries(res.reject_reasons).map(([k, cnt]) => `
        <div class="card" style="padding: 0.85rem; background: #0f172a; border: 1px solid #1e293b; text-align: center;">
          <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">${labels[k] || k}</div>
          <div style="font-size: 1.4rem; font-weight: bold; color: ${cnt > 0 ? '#ef4444' : '#64748b'}; margin-top: 0.25rem;">${cnt}</div>
        </div>
      `).join('');
    }
  } catch (err) {
    console.error('Failed to load analytics:', err);
  }
}

// CHAOS SIMULATION TRIGGER
async function triggerSimulateChaos() {
  const btn = document.getElementById('btn-simulate-chaos');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Simulating...';
  }
  try {
    const res = await api.post('/api/admin/simulate', {});
    let message = '⚡ DEMO CHAOS SIMULATION COMPLETE!\n\n';
    if (res.scenarios) {
      res.scenarios.forEach(s => {
        message += `✓ ${s.scenario}: ${s.details || 'Passed'}\n`;
      });
    }
    alert(message);
    await loadInitialData();
  } catch (err) {
    alert('Chaos simulation failed: ' + (err.message || 'Error'));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Simulate Chaos';
    }
  }
}

// RESET ALL SIMULATION DATA TO CLEAN SLATE
async function triggerResetData() {
  if (!confirm('Are you sure you want to remove all simulation and demo bookings? This restores the fleet to a clean initial state.')) {
    return;
  }
  const btn = document.getElementById('btn-reset-data');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Clearing...';
  }
  try {
    const res = await api.post('/api/admin/reset', {});
    alert(res.message || 'All simulation data and bookings wiped successfully!');
    await loadInitialData();
  } catch (err) {
    alert('Reset failed: ' + (err.message || 'Error'));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🗑️ Reset Data';
    }
  }
}

// Auto-poll approval queue every 6 seconds so requests appear in real time
setInterval(() => {
  const queueView = document.getElementById('view-queue');
  if (queueView && queueView.style.display !== 'none' && currentManagerProfile) {
    loadApprovalQueue();
  }
}, 6000);

