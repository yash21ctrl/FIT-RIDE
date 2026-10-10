/**
 * FleetRide Shared API Client (Team KNIGHT | PS 40)
 * Handles token storage, standard error payload parsing, and HTTP requests.
 */

class ApiError extends Error {
  constructor(message, code = 'API_ERROR', status = 500, alternatives = [], data = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.alternatives = alternatives || [];
    this.data = data;
  }
}

class FleetApiClient {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
    this.TOKEN_KEY = 'fleet_token';
    this.USER_KEY = 'fleet_user';
    this.ROLE_KEY = 'fleet_role';
    this._memStore = {};
    this.unauthorizedListeners = new Set();
  }

  onUnauthorized(cb) {
    this.unauthorizedListeners.add(cb);
    return () => this.unauthorizedListeners.delete(cb);
  }

  notifyUnauthorized() {
    for (const cb of this.unauthorizedListeners) {
      try {
        cb();
      } catch (e) {
        console.error('Error in unauthorized listener', e);
      }
    }
  }

  getToken() {
    try {
      const val = localStorage.getItem(this.TOKEN_KEY);
      if (val) return val;
    } catch {
      // fallback to memory
    }
    return this._memStore[this.TOKEN_KEY] || null;
  }

  getUser() {
    try {
      const raw = localStorage.getItem(this.USER_KEY);
      if (raw) return JSON.parse(raw);
    } catch {
      // fallback to memory
    }
    const memRaw = this._memStore[this.USER_KEY];
    return memRaw ? JSON.parse(memRaw) : null;
  }

  getRole() {
    try {
      const role = localStorage.getItem(this.ROLE_KEY);
      if (role) return role;
    } catch {
      // fallback
    }
    return this._memStore[this.ROLE_KEY] || (this.getUser() && this.getUser().role) || null;
  }

  setAuth(token, user, role) {
    const userRole = role || (user && user.role) || '';
    if (token) this._memStore[this.TOKEN_KEY] = token;
    if (user) this._memStore[this.USER_KEY] = JSON.stringify(user);
    if (userRole) this._memStore[this.ROLE_KEY] = userRole;

    try {
      if (token) localStorage.setItem(this.TOKEN_KEY, token);
      if (user) localStorage.setItem(this.USER_KEY, JSON.stringify(user));
      if (userRole) localStorage.setItem(this.ROLE_KEY, userRole);
    } catch (e) {
      console.warn('LocalStorage error while saving auth (using memory store)', e);
    }
  }

  clearAuth() {
    this._memStore = {};
    try {
      localStorage.removeItem(this.TOKEN_KEY);
      localStorage.removeItem(this.USER_KEY);
      localStorage.removeItem(this.ROLE_KEY);
    } catch (e) {
      console.warn('LocalStorage error while clearing auth', e);
    }
  }

  clearToken() {
    this.clearAuth();
  }

  isAuthenticated() {
    return Boolean(this.getToken());
  }

  async request(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${this.baseUrl}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };

    const token = this.getToken();
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const config = {
      ...options,
      headers,
    };

    if (config.body && typeof config.body === 'object' && !(config.body instanceof FormData)) {
      config.body = JSON.stringify(config.body);
    }

    let response;
    try {
      response = await fetch(url, config);
    } catch (networkErr) {
      throw new ApiError(
        networkErr.message || 'Network error: could not connect to server',
        'NETWORK_ERROR',
        0
      );
    }

    let data = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        data = await response.json();
      } catch {
        data = null;
      }
    } else {
      try {
        data = await response.text();
      } catch {
        data = null;
      }
    }

    if (!response.ok) {
      // Check for standardized error payload matching SPEC.md Section 9:
      // { "error": { "code": "...", "message": "...", "alternatives": [] } }
      let errorCode = 'HTTP_' + response.status;
      let errorMsg = `Request failed with status ${response.status}`;
      let alternatives = [];

      if (data && typeof data === 'object') {
        if (data.error) {
          errorCode = data.error.code || errorCode;
          errorMsg = data.error.message || errorMsg;
          alternatives = data.error.alternatives || data.alternatives || [];
        } else if (data.failure_reason) {
          errorCode = data.failure_reason;
          errorMsg = `Allocation failed: ${data.failure_reason}`;
          alternatives = data.alternatives || [];
        } else if (data.message) {
          errorMsg = data.message;
        }
      }

      // If token expired or unauthorized, trigger logout if needed
      if (response.status === 401 && endpoint !== '/api/auth/login') {
        this.clearAuth();
        this.notifyUnauthorized();
      }

      throw new ApiError(errorMsg, errorCode, response.status, alternatives, data);
    }

    return data;
  }

  get(endpoint, params = null) {
    let finalUrl = endpoint;
    if (params && typeof params === 'object') {
      const qs = new URLSearchParams();
      for (const [key, val] of Object.entries(params)) {
        if (val !== undefined && val !== null) {
          qs.append(key, val);
        }
      }
      const qsStr = qs.toString();
      if (qsStr) {
        finalUrl += (finalUrl.includes('?') ? '&' : '?') + qsStr;
      }
    }
    return this.request(finalUrl, { method: 'GET' });
  }

  post(endpoint, body = {}) {
    return this.request(endpoint, { method: 'POST', body });
  }

  patch(endpoint, body = {}) {
    return this.request(endpoint, { method: 'PATCH', body });
  }

  del(endpoint) {
    return this.request(endpoint, { method: 'DELETE' });
  }

  // Auth shortcuts
  async login(identifier, password = '123', profileId = null) {
    const payload = {
      id: identifier,
      username: identifier,
      email: identifier,
      password: password || '123'
    };
    if (profileId) payload.profile_id = profileId;

    const res = await this.post('/api/auth/login', payload);
    if (res && (res.access_token || res.token)) {
      const token = res.access_token || res.token;
      this.setAuth(token, res.user || res.profile, res.role);
    }
    return res;
  }

  async fetchMe() {
    const res = await this.get('/api/me');
    if (res && res.profile) {
      this.setAuth(this.getToken(), res.profile, res.role);
    }
    return res;
  }

  logout() {
    this.clearAuth();
  }
}

// Global XSS defense helper
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

window.escapeHtml = escapeHtml;

// Global singleton instance for shared usage
window.api = new FleetApiClient();
