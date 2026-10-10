/**
 * FIT-RIDE Realtime Updates & Notification Poller (Team KNIGHT | PS 40)
 * Keeps booking statuses and notifications fresh using polling and optional Realtime.
 */

class FleetRealtimeManager {
  constructor(apiClient) {
    this.api = apiClient || window.api;
    this.pollIntervalMs = 6000;
    this.timer = null;
    this.isRunning = false;

    this.notificationListeners = new Set();
    this.bookingListeners = new Set();
    this.alertListeners = new Set();

    this.lastBookingsMap = new Map();
    this.knownNotificationIds = new Set();

    this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this.handleVisibilityChange);
    }
  }

  handleVisibilityChange() {
    if (document.hidden) {
      // Slow down polling when in background
      if (this.isRunning) {
        clearInterval(this.timer);
        this.timer = setInterval(() => this.poll(), 20000);
      }
    } else {
      // Speed up immediately when focused
      if (this.isRunning) {
        clearInterval(this.timer);
        this.poll();
        this.timer = setInterval(() => this.poll(), this.pollIntervalMs);
      }
    }
  }

  onNotifications(callback) {
    this.notificationListeners.add(callback);
    return () => this.notificationListeners.delete(callback);
  }

  onBookings(callback) {
    this.bookingListeners.add(callback);
    return () => this.bookingListeners.delete(callback);
  }

  onAlert(callback) {
    this.alertListeners.add(callback);
    return () => this.alertListeners.delete(callback);
  }

  start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.poll();
    this.timer = setInterval(() => this.poll(), this.pollIntervalMs);
  }

  stop() {
    this.isRunning = false;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  async poll() {
    if (!this.api || !this.api.isAuthenticated()) {
      return;
    }

    // 1. Fetch Notifications
    try {
      const notifData = await this.api.get('/api/notifications');
      if (notifData && Array.isArray(notifData.notifications)) {
        const notifs = notifData.notifications;
        const unreadCount = notifData.unread_count || notifs.filter((n) => !n.read).length;

        // Check for new notifications to trigger alerts
        for (const n of notifs) {
          if (!this.knownNotificationIds.has(n.id)) {
            this.knownNotificationIds.add(n.id);
            if (!n.read) {
              this.emitAlert({
                title: 'Fleet Update',
                message: n.message,
                type: 'info',
                bookingId: n.booking_id,
              });
            }
          }
        }

        for (const cb of this.notificationListeners) {
          try {
            cb(notifs, unreadCount);
          } catch (e) {
            console.error('Error in notification listener', e);
          }
        }
      }
    } catch (err) {
      if (err && (err.status === 401 || err.code === 'UNAUTHORIZED')) {
        this.stop();
        return;
      }
    }

    // 2. Fetch My Bookings to track live status transitions
    try {
      const bookingData = await this.api.get('/api/bookings/mine');
      if (bookingData && Array.isArray(bookingData.bookings)) {
        const bookings = bookingData.bookings;

        // Detect status mutations
        for (const b of bookings) {
          const prevStatus = this.lastBookingsMap.get(b.id);
          if (prevStatus && prevStatus !== b.status) {
            this.emitAlert({
              title: `Trip ${b.destination || ''}`,
              message: `Status updated from ${prevStatus} to ${b.status}!`,
              type: b.status === 'CONFIRMED' || b.status === 'APPROVED' ? 'success' : 'status_change',
              bookingId: b.id,
            });
          }
          this.lastBookingsMap.set(b.id, b.status);
        }

        for (const cb of this.bookingListeners) {
          try {
            cb(bookings);
          } catch (e) {
            console.error('Error in booking listener', e);
          }
        }
      }
    } catch (err) {
      if (err && (err.status === 401 || err.code === 'UNAUTHORIZED')) {
        this.stop();
        return;
      }
    }
  }

  emitAlert(alertObj) {
    for (const cb of this.alertListeners) {
      try {
        cb(alertObj);
      } catch (e) {
        console.error('Error in alert listener', e);
      }
    }
  }
}

window.realtime = new FleetRealtimeManager(window.api);
