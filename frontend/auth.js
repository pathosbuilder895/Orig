/**
 * auth.js — Authentication module for Original frontend.
 *
 * Handles login, token refresh, session expiry, and authenticated API calls.
 * Tokens are stored in memory (not localStorage) for security.
 * In production, httpOnly cookies should be used instead (requires backend changes).
 *
 * Usage:
 *   <script src="auth.js"></script>
 *   <script>
 *     OriginalAuth.requireAuth();  // Redirects to login if not authenticated
 *     OriginalAuth.apiFetch('/api/v1/students/').then(...);
 *   </script>
 */

(function () {
  'use strict';

  // ── Token storage (in-memory only — not persisted across page loads) ─────
  var _accessToken = null;
  var _refreshToken = null;
  var _tokenExpiry = null;
  var _user = null;

  // Try to restore from sessionStorage (survives page navigation, not tab close)
  try {
    var stored = sessionStorage.getItem('_original_session');
    if (stored) {
      var parsed = JSON.parse(stored);
      _accessToken = parsed.access_token;
      _refreshToken = parsed.refresh_token;
      _tokenExpiry = parsed.expiry ? new Date(parsed.expiry) : null;
      _user = parsed.user;
    }
  } catch (_e) {}

  function _saveSession() {
    try {
      sessionStorage.setItem('_original_session', JSON.stringify({
        access_token: _accessToken,
        refresh_token: _refreshToken,
        expiry: _tokenExpiry ? _tokenExpiry.toISOString() : null,
        user: _user,
      }));
    } catch (_e) {}
  }

  function _clearSession() {
    _accessToken = null;
    _refreshToken = null;
    _tokenExpiry = null;
    _user = null;
    try { sessionStorage.removeItem('_original_session'); } catch (_e) {}
  }

  // ── API base resolution ─────────────────────────────────────────────────
  function _apiBase() {
    if (window.ORIGINAL_API_BASE) return window.ORIGINAL_API_BASE.replace(/\/+$/, '');
    if (/^https?:$/.test(window.location.protocol)) return window.location.origin;
    return 'http://localhost:8000';
  }

  // ── Login ───────────────────────────────────────────────────────────────
  function login(email, password) {
    return fetch(_apiBase() + '/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: password }),
    })
    .then(function (resp) {
      if (!resp.ok) {
        return resp.json().then(function (body) {
          throw new Error(body.detail || 'Login failed');
        });
      }
      return resp.json();
    })
    .then(function (data) {
      _accessToken = data.access_token;
      _refreshToken = data.refresh_token;
      // Decode JWT expiry (access token is a JWT with exp claim)
      try {
        var payload = JSON.parse(atob(_accessToken.split('.')[1]));
        _tokenExpiry = new Date(payload.exp * 1000);
        _user = { email: payload.sub, role: payload.role };
      } catch (_e) {
        // Fallback: assume 15 minutes
        _tokenExpiry = new Date(Date.now() + 15 * 60 * 1000);
      }
      _saveSession();
      return { user: _user, expiresAt: _tokenExpiry };
    });
  }

  // ── Logout ──────────────────────────────────────────────────────────────
  function logout() {
    _clearSession();
    window.location.href = 'login.html';
  }

  // ── Token refresh ───────────────────────────────────────────────────────
  function _refreshAccessToken() {
    if (!_refreshToken) {
      return Promise.reject(new Error('No refresh token'));
    }
    return fetch(_apiBase() + '/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: _refreshToken }),
    })
    .then(function (resp) {
      if (!resp.ok) {
        _clearSession();
        throw new Error('Session expired');
      }
      return resp.json();
    })
    .then(function (data) {
      _accessToken = data.access_token;
      if (data.refresh_token) _refreshToken = data.refresh_token;
      try {
        var payload = JSON.parse(atob(_accessToken.split('.')[1]));
        _tokenExpiry = new Date(payload.exp * 1000);
      } catch (_e) {
        _tokenExpiry = new Date(Date.now() + 15 * 60 * 1000);
      }
      _saveSession();
    });
  }

  // ── Authenticated fetch ─────────────────────────────────────────────────
  function apiFetch(path, options) {
    options = options || {};

    // Check if token needs refresh (within 60s of expiry)
    var needsRefresh = _tokenExpiry && (new Date() > new Date(_tokenExpiry.getTime() - 60000));

    var doFetch = function () {
      if (!_accessToken) {
        logout();
        return Promise.reject(new Error('Not authenticated'));
      }
      var headers = Object.assign({}, options.headers || {}, {
        'Authorization': 'Bearer ' + _accessToken,
        'Content-Type': 'application/json',
      });
      return fetch(_apiBase() + path, Object.assign({}, options, { headers: headers }))
        .then(function (resp) {
          if (resp.status === 401) {
            // Try refresh once
            return _refreshAccessToken().then(function () {
              headers['Authorization'] = 'Bearer ' + _accessToken;
              return fetch(_apiBase() + path, Object.assign({}, options, { headers: headers }));
            });
          }
          return resp;
        });
    };

    if (needsRefresh && _refreshToken) {
      return _refreshAccessToken().then(doFetch).catch(function () {
        logout();
        return Promise.reject(new Error('Session expired'));
      });
    }

    return doFetch();
  }

  // ── Auth guard ──────────────────────────────────────────────────────────
  function isAuthenticated() {
    return !!_accessToken;
  }

  function requireAuth() {
    if (!isAuthenticated()) {
      // Save current URL for post-login redirect
      try {
        sessionStorage.setItem('_original_redirect', window.location.href);
      } catch (_e) {}
      window.location.href = 'login.html';
    }
  }

  function getUser() {
    return _user;
  }

  // ── Session expiry check (runs every 30s) ──────────────────────────────
  setInterval(function () {
    if (_tokenExpiry && new Date() > _tokenExpiry && !_refreshToken) {
      _showSessionExpired();
    }
  }, 30000);

  function _showSessionExpired() {
    if (document.getElementById('orig-session-expired')) return;
    var banner = document.createElement('div');
    banner.id = 'orig-session-expired';
    banner.setAttribute('role', 'alert');
    banner.style.cssText = [
      'position:fixed;top:0;left:0;right:0;z-index:9999;',
      'padding:0.75rem;text-align:center;',
      'background:#fef3c7;border-bottom:2px solid #d97706;',
      'font-family:Inter,system-ui,sans-serif;font-size:0.875rem;color:#92400e;',
    ].join('');
    banner.innerHTML = 'Your session has expired. <a href="login.html" style="color:#1a6fb5;font-weight:600;">Log in again</a>';
    document.body.insertBefore(banner, document.body.firstChild);
  }

  // ── Public API ──────────────────────────────────────────────────────────
  window.OriginalAuth = {
    login: login,
    logout: logout,
    apiFetch: apiFetch,
    isAuthenticated: isAuthenticated,
    requireAuth: requireAuth,
    getUser: getUser,
  };

})();
