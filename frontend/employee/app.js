/**
 * FIT-RIDE Employee Portal Application (Team KNIGHT | PS 40)
 * Single-page experience with deterministic allocation result explanation,
 * failure ladder alternatives, waitlisting, and realtime notifications.
 */

class EmployeeApp {
  constructor() {
    this.api = window.api;
    this.time = window.FleetTime;
    this.realtime = window.realtime;

    this.currentView = 'login';
    this.bookingType = 'scheduled';
    this.bookingPriority = 'normal';
    this.durationMinutes = 120;

    this.allTrips = [];
    this.activeFilter = 'ALL';
    this.lastSubmittedForm = null;
    this.lastFailureResult = null;

    this.vehiclesCache = new Map();
    this.driversCache = new Map();

    this.init();
  }

  async init() {
    this.initFormDefaults();

    // Setup realtime event subscriptions
    this.realtime.onNotifications((notifs, unreadCount) => {
      this.renderNotifications(notifs, unreadCount);
    });

    this.realtime.onBookings((bookings) => {
      this.allTrips = bookings;
      if (this.currentView === 'trips') {
        this.renderTripsList();
      }
    });

    this.realtime.onAlert((alertObj) => {
      this.showToast(alertObj.message, alertObj.type);
    });

    // Auto-logout when token expires
    this.api.onUnauthorized(() => {
      this.realtime.stop();
      this.showView('login');
      this.showToast('Session expired. Please sign in again.', 'info');
    });

    // Check existing auth state
    if (this.api.isAuthenticated()) {
      try {
        const me = await this.api.fetchMe();
        const user = me.user || me.profile || this.api.getUser();
        this.onLoginSuccess(user);
      } catch {
        this.api.logout();
        this.showView('login');
      }
    } else {
      this.showView('login');
    }
  }

  // --- View Switcher ---
  showView(viewName) {
    this.currentView = viewName;

    const views = ['login', 'book', 'result', 'trips'];
    views.forEach((v) => {
      const el = document.getElementById(`view-${v}`);
      if (el) el.style.display = v === viewName ? 'block' : 'none';
    });

    // Toggle Nav header
    const navEl = document.getElementById('nav-section');
    if (navEl) {
      navEl.style.display = viewName === 'login' ? 'none' : 'flex';
    }

    // Toggle tab active states
    const bookTab = document.getElementById('tab-book-btn');
    const tripsTab = document.getElementById('tab-trips-btn');
    if (bookTab) bookTab.classList.toggle('active', viewName === 'book' || viewName === 'result');
    if (tripsTab) tripsTab.classList.toggle('active', viewName === 'trips');

    if (viewName === 'trips') {
      this.loadMyTrips();
    }
  }

  // --- Auth Handlers ---
  async handleLoginSubmit(event) {
    event.preventDefault();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const btn = document.getElementById('login-submit-btn');

    try {
      btn.disabled = true;
      btn.textContent = 'Signing In...';
      const res = await this.api.login(email, password);
      this.onLoginSuccess(res.user || res.profile);
    } catch (err) {
      this.showToast(err.message || 'Login failed', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Sign In';
    }
  }

  async quickLogin(identifier) {
    document.getElementById('login-email').value = identifier;
    try {
      const res = await this.api.login(identifier, '123');
      this.onLoginSuccess(res.user || res.profile);
    } catch (err) {
      this.showToast(err.message || 'Quick login failed', 'error');
    }
  }

  onLoginSuccess(user) {
    const safeUser = user || {};
    if (safeUser.role === 'driver') {
      this.api.clearAuth();
      this.showToast('Access Denied: Drivers should use the Driver Portal (/driver).', 'error');
      this.showView('login');
      return;
    }
    const nameEl = document.getElementById('user-display-name');
    const avatarEl = document.getElementById('user-avatar');
    const name = safeUser.name || 'Employee';
    if (nameEl) nameEl.textContent = name;
    if (avatarEl) avatarEl.textContent = name.charAt(0).toUpperCase();

    this.showToast(`Welcome back, ${name}!`, 'success');
    this.realtime.start();
    this.showView('book');
  }

  logout() {
    this.realtime.stop();
    this.api.logout();
    this.showView('login');
    this.showToast('Signed out successfully.', 'info');
  }

  // --- Form Controls & Presets ---
  initFormDefaults() {
    const slot = this.time.getNextAvailableSlot(30);
    const dateInput = document.getElementById('book-date');
    const startInput = document.getElementById('book-start-time');
    const endInput = document.getElementById('book-end-time');
    const destInput = document.getElementById('book-destination');

    if (dateInput) {
      dateInput.value = slot.dateStr;
      dateInput.min = slot.dateStr;
    }
    if (startInput) {
      startInput.value = slot.timeStr;
    }

    this.updateCalculatedEndTime();

    // Listen to changes on start time, date, end time, and destination
    if (startInput) {
      startInput.addEventListener('change', () => this.updateCalculatedEndTime());
    }
    if (dateInput) {
      dateInput.addEventListener('change', () => this.updateScheduleSummary());
    }
    if (endInput) {
      endInput.addEventListener('change', () => this.handleEndTimeChange());
    }
    if (destInput) {
      destInput.addEventListener('input', () => this.updateScheduleSummary());
    }
  }

  setBookingType(type) {
    this.bookingType = type;
    this.bookingPriority = type === 'emergency' ? 'emergency' : 'normal';

    const schedOpt = document.getElementById('type-opt-scheduled');
    const emergOpt = document.getElementById('type-opt-emergency');
    const banner = document.getElementById('emergency-banner');
    const btn = document.getElementById('book-submit-btn');
    const btnText = document.getElementById('submit-btn-text');

    if (type === 'emergency') {
      schedOpt.classList.remove('selected');
      emergOpt.classList.add('selected', 'emergency-selected');
      if (banner) banner.style.display = 'flex';
      if (btn) {
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-emergency');
      }
      if (btnText) btnText.textContent = '🚨 Dispatch Emergency Vehicle';
    } else {
      emergOpt.classList.remove('selected', 'emergency-selected');
      schedOpt.classList.add('selected');
      if (banner) banner.style.display = 'none';
      if (btn) {
        btn.classList.remove('btn-emergency');
        btn.classList.add('btn-primary');
      }
      if (btnText) btnText.textContent = 'Submit Booking Request';
    }
  }

  setDuration(mins) {
    this.durationMinutes = mins;
    const durDisplay = document.getElementById('duration-display');
    if (durDisplay) {
      const h = Math.floor(mins / 60);
      const m = mins % 60;
      durDisplay.textContent = h > 0 ? (m > 0 ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
    }

    // Highlight preset pill
    const pills = document.querySelectorAll('#booking-form .preset-pills button');
    pills.forEach((p) => {
      const matchM = p.getAttribute('onclick')?.match(/setDuration\((\d+)\)/);
      if (matchM) {
        if (parseInt(matchM[1], 10) === mins) {
          p.classList.add('active');
        } else {
          p.classList.remove('active');
        }
      }
    });

    this.updateCalculatedEndTime();
  }

  updateCalculatedEndTime() {
    const dateStr = document.getElementById('book-date')?.value;
    const startTimeStr = document.getElementById('book-start-time')?.value;
    const endInput = document.getElementById('book-end-time');

    if (!dateStr || !startTimeStr || !endInput) return;

    try {
      const endObj = this.time.addDuration(dateStr, startTimeStr, this.durationMinutes);
      endInput.value = endObj.timeStr;
    } catch {
      // fallback
    }

    this.updateScheduleSummary();
  }

  handleEndTimeChange() {
    const startTimeStr = document.getElementById('book-start-time')?.value;
    const endTimeStr = document.getElementById('book-end-time')?.value;
    if (startTimeStr && endTimeStr) {
      const diff = this.time.diffMinutesLocal(startTimeStr, endTimeStr);
      if (diff > 0) {
        this.durationMinutes = diff;
        const durDisplay = document.getElementById('duration-display');
        if (durDisplay) {
          const h = Math.floor(diff / 60);
          const m = diff % 60;
          durDisplay.textContent = h > 0 ? (m > 0 ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
        }

        // Highlight matching duration pill if exact
        const pills = document.querySelectorAll('#booking-form .preset-pills button');
        pills.forEach((p) => {
          const matchM = p.getAttribute('onclick')?.match(/setDuration\((\d+)\)/);
          if (matchM) {
            if (parseInt(matchM[1], 10) === diff) {
              p.classList.add('active');
            } else {
              p.classList.remove('active');
            }
          }
        });
      }
    }
    this.updateScheduleSummary();
  }

  updateScheduleSummary() {
    const dateInput = document.getElementById('book-date');
    const startInput = document.getElementById('book-start-time');
    const endInput = document.getElementById('book-end-time');
    const destInput = document.getElementById('book-destination');

    const dateStr = dateInput ? dateInput.value : '';
    const startTimeStr = startInput ? startInput.value : '';
    const endTimeStr = endInput ? endInput.value : '';
    const destStr = destInput ? destInput.value.trim() : '';

    const dateDisplay = document.getElementById('summary-date-display');
    const startDisplay = document.getElementById('summary-start-display');
    const durationDisplay = document.getElementById('summary-duration-display');
    const endDisplay = document.getElementById('summary-end-display');
    const destNote = document.getElementById('summary-destination-note');

    if (dateDisplay && dateStr) {
      const todayStr = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
      if (dateStr === todayStr) {
        dateDisplay.textContent = 'Today (IST)';
      } else {
        const d = new Date(dateStr + 'T00:00:00+05:30');
        dateDisplay.textContent = d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short' });
      }
    }

    if (startDisplay && startTimeStr) {
      const [sh, sm] = startTimeStr.split(':').map(Number);
      const ampm = sh >= 12 ? 'PM' : 'AM';
      const h12 = sh % 12 || 12;
      startDisplay.textContent = `${String(h12).padStart(2, '0')}:${String(sm).padStart(2, '0')} ${ampm}`;
    }

    if (endDisplay && endTimeStr) {
      const [eh, em] = endTimeStr.split(':').map(Number);
      const ampm = eh >= 12 ? 'PM' : 'AM';
      const h12 = eh % 12 || 12;
      endDisplay.textContent = `${String(h12).padStart(2, '0')}:${String(em).padStart(2, '0')} ${ampm}`;
    }

    if (durationDisplay) {
      const h = Math.floor(this.durationMinutes / 60);
      const m = this.durationMinutes % 60;
      let durText = '';
      if (h > 0 && m > 0) durText = `${h}h ${m}m duration`;
      else if (h > 0) durText = `${h}h duration`;
      else durText = `${m}m duration`;
      durationDisplay.textContent = `⏱️ ${durText}`;
    }

    if (destNote) {
      if (destStr) {
        destNote.innerHTML = `<span>📍</span> Trip to <strong>${destStr}</strong>. Vehicle reserved from departure until return deadline. +15m buffer included after return.`;
      } else {
        destNote.innerHTML = `<span>💡</span> The vehicle and driver will be reserved for your team for the full duration above.`;
      }
    }
  }

  setPassengers(count, btn = null) {
    const input = document.getElementById('book-passengers');
    if (input) input.value = count;
    const container = input?.parentElement?.querySelector('.preset-pills');
    if (container) {
      container.querySelectorAll('.preset-pill').forEach((p) => p.classList.remove('active'));
    }
    if (btn) {
      btn.classList.add('active');
    } else if (container) {
      const match = Array.from(container.querySelectorAll('.preset-pill')).find((p) => p.textContent.trim().startsWith(String(count)));
      if (match) match.classList.add('active');
    }
  }

  setDestination(dest, mins = null, btn = null) {
    const input = document.getElementById('book-destination');
    if (input) input.value = dest;
    const container = input?.parentElement?.querySelector('.preset-pills');
    if (container) {
      container.querySelectorAll('.preset-pill').forEach((p) => p.classList.remove('active'));
    }
    if (btn) {
      btn.classList.add('active');
    } else if (container) {
      const match = Array.from(container.querySelectorAll('.preset-pill')).find((p) => p.textContent.includes(dest.trim()));
      if (match) match.classList.add('active');
    }

    if (mins) {
      this.setDuration(mins);
    } else {
      this.updateScheduleSummary();
    }
  }

  resetBookingForm() {
    document.getElementById('booking-form').reset();
    this.setBookingType('scheduled');
    this.setDuration(120);
    this.initFormDefaults();
  }

  // --- Booking Submission & Double Submit Guard ---
  async handleBookingSubmit(event) {
    event.preventDefault();

    const submitBtn = document.getElementById('book-submit-btn');
    const spinner = document.getElementById('submit-spinner');
    const btnText = document.getElementById('submit-btn-text');

    const dateStr = document.getElementById('book-date').value;
    const startTimeStr = document.getElementById('book-start-time').value;
    const endTimeStr = document.getElementById('book-end-time').value;
    const passengers = parseInt(document.getElementById('book-passengers').value, 10);
    const destination = document.getElementById('book-destination').value.trim();
    const reason = document.getElementById('book-reason').value.trim();

    if (!dateStr || !startTimeStr || !endTimeStr) {
      this.showToast('Please specify date, start time, and end time.', 'error');
      return;
    }

    // Convert Asia/Kolkata local times to UTC ISO strings, safely handling midnight crossings
    const startUtcIso = this.time.toUtcIso(dateStr, startTimeStr);
    const endUtcIso = this.time.calculateEndUtcIso(dateStr, startTimeStr, endTimeStr, this.durationMinutes);

    if (!startUtcIso || !endUtcIso || new Date(endUtcIso) <= new Date(startUtcIso)) {
      this.showToast('End time must be after start time.', 'error');
      return;
    }

    const payload = {
      start_time: startUtcIso,
      end_time: endUtcIso,
      passengers,
      destination,
      reason,
      type: this.bookingType,
      priority: this.bookingPriority,
    };

    this.lastSubmittedForm = {
      ...payload,
      dateStr,
      startTimeStr,
      endTimeStr,
    };

    // Double-submit prevention guard
    submitBtn.disabled = true;
    spinner.style.display = 'inline-block';
    const originalText = btnText.textContent;
    btnText.textContent = 'Allocating Fleet...';

    try {
      const res = await this.api.post('/api/bookings', payload);
      this.renderSuccessResult(res);
      this.showView('result');
      this.showToast('Booking successfully allocated!', 'success');
    } catch (err) {
      console.warn('Booking allocation returned conflict or failure', err);
      this.lastFailureResult = err;
      this.renderFailureResult(err, payload);
      this.showView('result');
    } finally {
      submitBtn.disabled = false;
      spinner.style.display = 'none';
      btnText.textContent = originalText;
    }
  }

  // --- Result Screen Rendering ---
  renderSuccessResult(res) {
    const booking = res.booking || {};
    const autoApproved = res.auto_approved;
    const options = res.options || [];
    const topOption = options[0] || {};

    const container = document.getElementById('result-content');
    if (!container) return;

    const startLocal = this.time.formatLocal(booking.start_time);
    const endLocal = this.time.formatLocal(booking.end_time);
    const durStr = this.time.formatDuration(booking.start_time, booking.end_time);

    const vehicleInfo = booking.vehicle_id ? this.formatVehicleInfo(booking.vehicle_id) : 'Fleet Vehicle';
    const driverInfo = booking.driver_id ? this.formatDriverInfo(booking.driver_id) : 'Fleet Driver';

    const decisionReason = booking.decision_reason || topOption.reason || 'Optimal vehicle fit based on passenger capacity and driver fairness.';

    container.innerHTML = `
      <div class="card">
        <div class="result-banner success">
          <div class="result-banner-icon">✓</div>
          <div>
            <div class="result-banner-title">
              ${autoApproved ? 'Auto-Approved & Dispatched to Driver!' : 'Trip Reserved (Awaiting Manager Review)'}
            </div>
            <div class="result-banner-desc">
              ${autoApproved
                ? 'Your booking qualified for instant auto-approval. Driver response timer is ticking.'
                : 'Your booking has soft-held the vehicle and is queued for manager sign-off.'}
            </div>
          </div>
        </div>

        <!-- Highlighted Plain-English Allocation Explanation -->
        <div class="decision-explanation-card">
          <div class="decision-badge">⚡ Deterministic Engine Rationale</div>
          <div class="decision-text">${escapeHtml(decisionReason)}</div>
        </div>

        <!-- Chosen Resource Summary -->
        <div class="resource-grid">
          <div class="resource-card">
            <div class="resource-title">Assigned Vehicle</div>
            <div class="resource-name">${escapeHtml(vehicleInfo)}</div>
            <div class="resource-meta">Capacity: ${booking.passengers} seats requested</div>
          </div>

          <div class="resource-card">
            <div class="resource-title">Assigned Driver</div>
            <div class="resource-name">${escapeHtml(driverInfo)}</div>
            <div class="resource-meta">Dispatched via fairness ranking</div>
          </div>

          <div class="resource-card">
            <div class="resource-title">Schedule Window</div>
            <div class="resource-name">${startLocal} ➔ ${endLocal}</div>
            <div class="resource-meta">⏱️ Total Duration: ${durStr} · Return by ${endLocal}</div>
          </div>
        </div>

        ${options.length > 1 ? `
          <div style="margin-top: 1.25rem; background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 1rem;">
            <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-secondary); margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 0.04em;">
              Alternative Candidates Evaluated (Runner-ups)
            </div>
            ${options.slice(1).map((opt, idx) => `
              <div style="font-size: 0.85rem; color: var(--text-muted); padding: 0.4rem 0; border-top: 1px solid var(--border-subtle);">
                <strong>Option ${idx + 2}:</strong> ${escapeHtml(this.formatVehicleInfo(opt.vehicle_id))} + ${escapeHtml(this.formatDriverInfo(opt.driver_id))}
                <span style="display: block; font-size: 0.8rem; color: var(--text-dim); margin-top: 0.15rem;">
                  Score: ${opt.score !== undefined ? Number(opt.score).toFixed(1) : '—'} — ${escapeHtml(opt.reason || '')}
                </span>
              </div>
            `).join('')}
          </div>
        ` : ''}

        <div style="margin-top: 1.5rem; display: flex; gap: 0.75rem; justify-content: flex-end;">
          <button class="btn btn-secondary" onclick="app.showView('book')">Book Another Trip</button>
          <button class="btn btn-primary" onclick="app.showView('trips')">View in My Trips ➔</button>
        </div>
      </div>
    `;
  }

  formatAlternativeTitle(type) {
    const titles = {
      shifted_window: 'Shifted Time Slot',
      shorter_duration: 'Shorter Duration Option',
      next_free_slot: 'Next Available Date / Time',
      split_recommendation: 'Group Split Recommendation',
      waitlist_recommendation: 'Priority Waitlist Placement',
    };
    return titles[type] || 'Alternative Option';
  }

  formatAlternativeAction(alt) {
    if (alt.type === 'waitlist_recommendation') return 'Join Waitlist ➔';
    if (alt.type === 'split_recommendation') return 'Adjust to 12 Seats ➔';
    return 'Tap to Select Slot ➔';
  }

  renderFailureResult(err, originalPayload) {
    const container = document.getElementById('result-content');
    if (!container) return;

    const failureReason = err.code || 'ALLOCATION_FAILED';
    const alternatives = err.alternatives || [];

    // Diagnose plain-English explanations per SPEC.md Section 4.4
    let failureTitle = 'Allocation Unavailable';
    let failureDesc = err.message || 'The fleet allocation engine could not find an available vehicle and rested driver.';

    if (failureReason === 'NO_VEHICLE_BIG_ENOUGH') {
      failureTitle = 'No Vehicle Large Enough';
      failureDesc = `No vehicle in the fleet can accommodate ${originalPayload.passengers} passengers. Fleet maximum capacity is 12 seats (Force Tempo Traveller).`;
    } else if (failureReason === 'ALL_VEHICLES_BUSY') {
      failureTitle = 'All Matching Vehicles Busy';
      failureDesc = 'All suitable vehicles in the fleet are already reserved for overlapping slots during this time window.';
    } else if (failureReason === 'NO_ELIGIBLE_DRIVER') {
      failureTitle = 'No Eligible Driver Available';
      failureDesc = 'Vehicles are available, but all drivers have either hit their 9-hour daily driving cap, lack the mandatory 45-minute rest gap, or are off-duty.';
    } else if (failureReason === 'VEHICLES_IN_MAINTENANCE') {
      failureTitle = 'Vehicles Under Maintenance';
      failureDesc = 'All vehicles meeting your seat requirements are currently flagged for scheduled maintenance.';
    } else if (failureReason === 'VEHICLE_TAKEN') {
      failureTitle = 'Concurrent Booking Conflict';
      failureDesc = 'That vehicle slot was just reserved by another request. Mutual exclusion constraint prevented a double-booking.';
    }

    let alternativesHtml = '';
    if (alternatives && alternatives.length > 0) {
      alternativesHtml = `
        <div class="alternatives-container">
          <h3 style="font-size: 1rem; color: var(--text-main); margin-bottom: 0.5rem;">Recommended Alternatives:</h3>
          <div class="alternatives-list">
            ${alternatives.map((alt, idx) => `
              <div class="alternative-card" onclick="app.selectAlternative(${idx})">
                <div>
                  <div class="alternative-slot-title">${escapeHtml(this.formatAlternativeTitle(alt.type))}</div>
                  <div class="alternative-slot-reason">
                    ${escapeHtml(alt.description || alt.reason || (alt.start && alt.end ? `${this.time.formatLocal(alt.start)} - ${this.time.formatLocal(alt.end)}` : 'Suggested slot'))}
                  </div>
                </div>
                <div class="alternative-tap-pill">${escapeHtml(this.formatAlternativeAction(alt))}</div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    } else {
      alternativesHtml = `
        <div style="font-size: 0.85rem; color: var(--text-muted); margin: 1rem 0;">
          No direct alternative slots found within the next 24 hours. Joining the waitlist guarantees priority when a vehicle frees up.
        </div>
      `;
    }

    container.innerHTML = `
      <div class="card">
        <div class="result-banner failure">
          <div class="result-banner-icon">✕</div>
          <div>
            <div class="result-banner-title">${escapeHtml(failureTitle)}</div>
            <div class="result-banner-desc">${escapeHtml(failureDesc)}</div>
          </div>
        </div>

        <!-- Failure Diagnosis Box -->
        <div class="decision-explanation-card" style="border-left-color: #ef4444;">
          <div class="decision-badge" style="color: #f87171;">🔍 Engine Diagnosis: ${escapeHtml(failureReason)}</div>
          <div class="decision-text">${escapeHtml(failureDesc)}</div>
        </div>

        ${alternativesHtml}

        <!-- Prominent Waitlist Action Card -->
        <div class="waitlist-card">
          <div class="waitlist-info">
            <div class="waitlist-title">📋 Join Waitlist with Auto-Promotion</div>
            <div class="waitlist-desc">
              Our deterministic state machine monitors every trip cancellation, driver timeout, and completion.
              As soon as capacity opens up, your request will be promoted automatically in order of priority!
            </div>
          </div>
          <button class="btn btn-primary" onclick="app.joinWaitlistForCurrentRequest()">
            🔔 Notify Me (Join Waitlist)
          </button>
        </div>

        <div style="margin-top: 1.5rem; display: flex; gap: 0.75rem; justify-content: flex-end;">
          <button class="btn btn-secondary" onclick="app.showView('book')">Modify Booking Details</button>
        </div>
      </div>
    `;
  }

  // --- Alternative Selection ---
  async selectAlternative(altIndex) {
    const err = this.lastFailureResult;
    const alternatives = (err && err.alternatives) || [];
    const alt = alternatives[altIndex];
    if (!alt) return;

    if (alt.type === 'waitlist_recommendation') {
      return this.joinWaitlistForCurrentRequest();
    }

    if (alt.type === 'split_recommendation') {
      const maxCap = alt.max_vehicle_capacity || 12;
      this.setPassengers(maxCap);
      this.showView('book');
      this.showToast(`Set passenger count to fleet maximum (${maxCap}). Submit this trip first, then book a second vehicle for the remaining passengers.`, 'info');
      return;
    }

    try {
      this.showToast('Booking selected alternative slot...', 'info');

      // If alternative has start and end times, update payload and submit
      const newPayload = {
        ...(this.lastSubmittedForm || {}),
        start_time: alt.start || this.lastSubmittedForm.start_time,
        end_time: alt.end || this.lastSubmittedForm.end_time,
      };

      if (alt.vehicle_id) newPayload.vehicle_id = alt.vehicle_id;
      if (alt.driver_id) newPayload.driver_id = alt.driver_id;

      const res = await this.api.post('/api/bookings', newPayload);
      this.renderSuccessResult(res);
      this.showToast('Alternative slot confirmed!', 'success');
    } catch (newErr) {
      this.showToast(newErr.message || 'Could not book alternative slot', 'error');
    }
  }

  // --- Waitlist Handler ---
  async joinWaitlistForCurrentRequest() {
    if (!this.lastSubmittedForm) {
      this.showToast('No booking parameters to waitlist', 'error');
      return;
    }

    try {
      this.showToast('Joining waitlist...', 'info');
      const payload = {
        ...this.lastSubmittedForm,
        waitlist: true,
        failure_reason: (this.lastFailureResult && this.lastFailureResult.code) || 'WAITLISTED',
      };

      const res = await this.api.post('/api/bookings', payload);
      this.showToast('You are on the waitlist! You will be notified on capacity release.', 'success');
      this.showView('trips');
    } catch (err) {
      this.showToast(err.message || 'Failed to join waitlist', 'error');
    }
  }

  // --- My Trips Management ---
  async loadMyTrips() {
    const container = document.getElementById('trips-list-container');
    if (!container) return;

    try {
      const res = await this.api.get('/api/bookings/mine');
      this.allTrips = res.bookings || [];
      this.renderTripsList();
    } catch (err) {
      container.innerHTML = `
        <div class="empty-state">
          <p style="color: #f87171;">Failed to load trips: ${escapeHtml(err.message)}</p>
          <button class="btn btn-secondary btn-sm" style="margin-top: 0.5rem;" onclick="app.loadMyTrips()">Retry</button>
        </div>
      `;
    }
  }

  filterTrips(filter, btn) {
    this.activeFilter = filter;
    const tabs = document.querySelectorAll('.trip-tab-btn');
    tabs.forEach((t) => t.classList.remove('active'));
    if (btn) btn.classList.add('active');
    this.renderTripsList();
  }

  renderTripsList() {
    const container = document.getElementById('trips-list-container');
    if (!container) return;

    let filtered = this.allTrips;
    if (this.activeFilter === 'ACTIVE') {
      filtered = this.allTrips.filter((t) => ['PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED', 'IN_PROGRESS'].includes(t.status));
    } else if (this.activeFilter === 'WAITLISTED') {
      filtered = this.allTrips.filter((t) => t.status === 'WAITLISTED');
    } else if (this.activeFilter === 'COMPLETED') {
      filtered = this.allTrips.filter((t) => t.status === 'COMPLETED');
    } else if (this.activeFilter === 'CANCELLED') {
      filtered = this.allTrips.filter((t) => ['CANCELLED', 'BUMPED', 'REJECTED'].includes(t.status));
    }

    if (!filtered || filtered.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🚗</div>
          <p>No trips found in this category.</p>
          <button class="btn btn-primary btn-sm" style="margin-top: 0.75rem;" onclick="app.showView('book')">
            Book a Trip Now
          </button>
        </div>
      `;
      return;
    }

    container.innerHTML = filtered.map((t) => this.renderTripCardHtml(t)).join('');
  }

  renderTripCardHtml(trip) {
    const badgeClass = `badge-${(trip.status || 'pending').toLowerCase().replace(/_/g, '-')}`;
    const startStr = this.time.formatLocal(trip.start_time);
    const endStr = this.time.formatLocal(trip.end_time);
    const durStr = this.time.formatDuration(trip.start_time, trip.end_time);
    const shortId = (trip.id || '').substring(0, 8);

    const isCancellable = ['PENDING', 'APPROVED', 'DRIVER_PENDING', 'CONFIRMED'].includes(trip.status);
    const isBumped = trip.status === 'BUMPED';

    const vehicleInfo = trip.vehicle_id ? this.formatVehicleInfo(trip.vehicle_id) : 'Pending Allocation';
    const driverInfo = trip.driver_id ? this.formatDriverInfo(trip.driver_id) : 'Pending Assignment';

    return `
      <div class="trip-card">
        <div class="trip-card-header">
          <div class="trip-dest">
            <span>📍</span>
            <span>${escapeHtml(trip.destination || 'Destination')}</span>
            <span class="trip-id-code">#${shortId}</span>
          </div>
          <div style="display: flex; gap: 0.4rem; align-items: center;">
            ${trip.type === 'emergency' ? '<span class="badge" style="background: rgba(234, 88, 12, 0.2); color: #fb923c; border-color: #ea580c;">🚨 Emergency</span>' : ''}
            <span class="badge ${badgeClass}">${escapeHtml(trip.status)}</span>
          </div>
        </div>

        <div class="trip-meta-grid">
          <div class="trip-meta-item">
            <span class="trip-meta-label">Schedule</span>
            <span>${startStr}</span>
            <span style="font-size: 0.75rem; color: var(--text-dim);">${durStr} (until ${endStr})</span>
          </div>

          <div class="trip-meta-item">
            <span class="trip-meta-label">Vehicle & Driver</span>
            <span>${escapeHtml(vehicleInfo)}</span>
            <span style="font-size: 0.75rem; color: var(--text-dim);">${escapeHtml(driverInfo)}</span>
          </div>

          <div class="trip-meta-item">
            <span class="trip-meta-label">Passengers & Reason</span>
            <span>${trip.passengers} Passengers</span>
            <span style="font-size: 0.75rem; color: var(--text-dim);">${escapeHtml(trip.reason || '—')}</span>
          </div>
        </div>

        ${trip.decision_reason ? `
          <div class="trip-engine-reason">
            <strong>Engine Note:</strong> ${escapeHtml(trip.decision_reason)}
          </div>
        ` : ''}

        <div class="trip-card-actions">
          ${isBumped ? `
            <button class="btn btn-secondary btn-sm" onclick="app.rebookTrip('${trip.id}')">
              Choose Alternative
            </button>
            <button class="btn btn-primary btn-sm" onclick="app.handleWaitlistBumped('${trip.id}')">
              Join Waitlist
            </button>
          ` : ''}

          ${trip.status === 'WAITLISTED' ? `
            <button class="btn btn-secondary btn-sm" onclick="app.rebookTrip('${trip.id}')">
              Try Different Slot
            </button>
          ` : ''}

          ${isCancellable ? `
            <button class="btn btn-danger btn-sm" onclick="app.cancelBooking('${trip.id}')">
              Cancel Trip
            </button>
          ` : ''}
        </div>
      </div>
    `;
  }

  rebookTrip(bookingId) {
    const trip = this.allTrips.find((t) => t.id === bookingId);
    if (!trip) return;

    this.showView('book');
    if (trip.destination) this.setDestination(trip.destination);
    if (trip.passengers) this.setPassengers(trip.passengers);
    const reasonEl = document.getElementById('book-reason');
    if (reasonEl && trip.reason) reasonEl.value = trip.reason;

    this.showToast('Trip parameters pre-filled. Select a new date/time slot.', 'info');
  }

  async cancelBooking(bookingId) {
    if (!confirm('Are you sure you want to cancel this trip? The reserved slot will be released.')) {
      return;
    }

    try {
      this.showToast('Cancelling booking...', 'info');
      await this.api.post(`/api/bookings/${bookingId}/cancel`, { note: 'Cancelled by employee' });
      this.showToast('Booking cancelled.', 'success');
      this.loadMyTrips();
    } catch (err) {
      this.showToast(err.message || 'Failed to cancel booking', 'error');
    }
  }

  async handleWaitlistBumped(bookingId) {
    try {
      this.showToast('Joining waitlist for bumped booking...', 'info');
      await this.api.post(`/api/bookings/${bookingId}/waitlist`, { note: 'Employee re-joined waitlist after bump' });
      this.showToast('Added to waitlist!', 'success');
      this.loadMyTrips();
    } catch (err) {
      this.showToast(err.message || 'Waitlist request failed', 'error');
    }
  }

  // --- Vehicle & Driver Format Helpers ---
  formatVehicleInfo(vehicleId) {
    const known = {
      '00000000-0000-0000-0001-000000000001': 'Maruti Swift (4 seats)',
      '00000000-0000-0000-0001-000000000002': 'Honda City (4 seats)',
      '00000000-0000-0000-0001-000000000003': 'Maruti Ertiga (7 seats)',
      '00000000-0000-0000-0001-000000000004': 'Toyota Innova Crysta (7 seats)',
      '00000000-0000-0000-0001-000000000005': 'Mahindra Bolero (7 seats)',
      '00000000-0000-0000-0001-000000000006': 'Force Tempo Traveller (12 seats)',
    };
    return known[vehicleId] || `Vehicle (${(vehicleId || '').substring(0, 8)})`;
  }

  formatDriverInfo(driverId) {
    const known = {
      '00000000-0000-0000-0005-000000000001': 'Ravi Kumar (★ 4.8)',
      '00000000-0000-0000-0005-000000000002': 'Suresh Patil (★ 4.9)',
      '00000000-0000-0000-0005-000000000003': 'Amit Singh (★ 4.7)',
      '00000000-0000-0000-0005-000000000004': 'Priya Sharma (★ 4.6)',
      '00000000-0000-0000-0005-000000000005': 'Rajesh Verma (★ 4.9)',
    };
    return known[driverId] || `Driver (${(driverId || '').substring(0, 8)})`;
  }

  // --- Notifications Drawer ---
  toggleNotifications() {
    const drawer = document.getElementById('notif-drawer-backdrop');
    if (drawer) {
      drawer.classList.toggle('open');
    }
  }

  closeNotifications() {
    const drawer = document.getElementById('notif-drawer-backdrop');
    if (drawer) {
      drawer.classList.remove('open');
    }
  }

  renderNotifications(notifs, unreadCount) {
    const badge = document.getElementById('notif-badge');
    if (badge) {
      if (unreadCount > 0) {
        badge.style.display = 'flex';
        badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
      } else {
        badge.style.display = 'none';
      }
    }

    const listEl = document.getElementById('notif-list');
    if (!listEl) return;

    if (!notifs || notifs.length === 0) {
      listEl.innerHTML = `
        <div class="empty-state">
          <p>No notifications yet</p>
        </div>
      `;
      return;
    }

    listEl.innerHTML = notifs.map((n) => `
      <div class="notif-item ${n.read ? '' : 'unread'}" onclick="app.markNotificationRead('${n.id}')">
        <div class="notif-message">${escapeHtml(n.message)}</div>
        <div class="notif-time">${this.time.formatLocal(n.created_at)}</div>
      </div>
    `).join('');
  }

  async markNotificationRead(notifId) {
    try {
      await this.api.post(`/api/notifications/${notifId}/read`);
      this.realtime.poll();
    } catch {
      // silent
    }
  }

  async markAllNotificationsRead() {
    try {
      await this.api.post('/api/notifications/read-all');
      this.realtime.poll();
      this.showToast('All notifications marked as read', 'info');
    } catch {
      // silent
    }
  }

  // --- Toast Alerts ---
  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';

    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '⚠️';
    if (type === 'status_change') icon = '🔔';

    toast.innerHTML = `<span style="margin-right: 0.4rem;">${icon}</span> ${escapeHtml(message)}`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 200ms ease-out';
      setTimeout(() => toast.remove(), 250);
    }, 4000);
  }
}

// Utility to escape HTML strings safely
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

window.app = new EmployeeApp();
