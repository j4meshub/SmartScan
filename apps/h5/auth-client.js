const SESSION_KEY = "smartscan.auth.session.v1";
const DEVICE_KEY = "smartscan.device.id.v1";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function randomDeviceSuffix(cryptoApi) {
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  if (typeof cryptoApi?.getRandomValues !== "function") {
    throw new Error("secure_random_unavailable");
  }
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function getOrCreateDeviceId(storage, cryptoApi = globalThis.crypto) {
  const existing = storage.getItem(DEVICE_KEY);
  if (/^web:[A-Za-z0-9_.:-]{4,60}$/.test(existing || "")) return existing;
  const deviceId = `web:${randomDeviceSuffix(cryptoApi)}`;
  storage.setItem(DEVICE_KEY, deviceId);
  return deviceId;
}

export function deviceHeaders(deviceId, deviceName = "SmartScan H5") {
  return {
    "X-Device-ID": deviceId,
    "X-Device-Name": encodeURIComponent(deviceName.slice(0, 100)),
    "X-Device-Platform": "web",
  };
}

async function responsePayload(response) {
  if (response.status === 204) return null;
  return response.json().catch(() => ({}));
}

export class AuthClient {
  constructor({
    api,
    fetchImpl = globalThis.fetch,
    sessionStorage,
    deviceStorage,
    cryptoApi = globalThis.crypto,
    deviceName = "SmartScan H5",
    onAuthLost = () => {},
  }) {
    this.api = api.replace(/\/$/, "");
    this.fetchImpl = fetchImpl;
    this.sessionStorage = sessionStorage;
    this.deviceId = getOrCreateDeviceId(deviceStorage, cryptoApi);
    this.deviceName = deviceName;
    this.onAuthLost = onAuthLost;
    this.refreshPromise = null;
  }

  get session() {
    try {
      return JSON.parse(this.sessionStorage.getItem(SESSION_KEY)) || null;
    } catch {
      this.clearSession();
      return null;
    }
  }

  get isAuthenticated() {
    return Boolean(this.session?.access_token);
  }

  setSession(payload) {
    if (!payload?.access_token) throw new Error("access_token_missing");
    const next = {
      access_token: payload.access_token,
      expires_at: payload.expires_at || null,
      refresh_token: payload.refresh_token || null,
      refresh_expires_at: payload.refresh_expires_at || null,
      session_id: payload.session_id || null,
      device_id: payload.device_id || this.deviceId,
    };
    this.sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
    return next;
  }

  clearSession() {
    this.sessionStorage.removeItem(SESSION_KEY);
  }

  async fetchResponse(path, options = {}, {auth = true} = {}) {
    const headers = {...deviceHeaders(this.deviceId, this.deviceName), ...(options.headers || {})};
    const session = this.session;
    if (auth && session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
    if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    return this.fetchImpl(`${this.api}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });
  }

  async request(path, options = {}, {auth = true, retry = true} = {}) {
    let response = await this.fetchResponse(path, options, {auth});
    if (response.status === 401 && auth && retry && this.session?.refresh_token) {
      await this.refresh();
      response = await this.fetchResponse(path, options, {auth});
    }
    const payload = await responsePayload(response);
    if (!response.ok) {
      if (response.status === 401 && auth) {
        this.clearSession();
        this.onAuthLost();
      }
      throw new ApiError(payload?.detail || `HTTP ${response.status}`, response.status);
    }
    return payload;
  }

  async requestBlob(path, options = {}, {retry = true} = {}) {
    let response = await this.fetchResponse(path, options, {auth: true});
    if (response.status === 401 && retry && this.session?.refresh_token) {
      await this.refresh();
      response = await this.fetchResponse(path, options, {auth: true});
    }
    if (!response.ok) {
      const payload = await responsePayload(response);
      if (response.status === 401) {
        this.clearSession();
        this.onAuthLost();
      }
      throw new ApiError(payload?.detail || `HTTP ${response.status}`, response.status);
    }
    return response.blob();
  }

  async refresh() {
    if (this.refreshPromise) return this.refreshPromise;
    const refreshToken = this.session?.refresh_token;
    if (!refreshToken) throw new ApiError("refresh_token_missing", 401);
    this.refreshPromise = (async () => {
      const response = await this.fetchResponse(
        "/v1/auth/refresh",
        {method: "POST", body: JSON.stringify({refresh_token: refreshToken})},
        {auth: false},
      );
      const payload = await responsePayload(response);
      if (!response.ok) {
        this.clearSession();
        this.onAuthLost();
        throw new ApiError(payload?.detail || `HTTP ${response.status}`, response.status);
      }
      if (!payload?.access_token || !payload?.refresh_token) {
        this.clearSession();
        this.onAuthLost();
        throw new ApiError("refresh_response_invalid", 502);
      }
      return this.setSession(payload);
    })();
    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }

  async login(username, password) {
    const payload = await this.request(
      "/v1/auth/login",
      {method: "POST", body: JSON.stringify({username, password})},
      {auth: false},
    );
    return this.setSession(payload);
  }

  async beginWeCom() {
    return this.request("/v1/auth/wecom/authorize", {method: "POST"}, {auth: false});
  }

  async completeWeComCallback(code, state) {
    const query = new URLSearchParams({code, state});
    const payload = await this.request(
      `/v1/auth/wecom/callback?${query}`,
      {},
      {auth: false},
    );
    if (payload.access_token) this.setSession(payload);
    return payload;
  }

  async requestBindingCode(phone) {
    return this.request(
      "/v1/auth/sms/challenges",
      {method: "POST", body: JSON.stringify({phone, purpose: "wecom_binding"})},
      {auth: false},
    );
  }

  async bindWeComPhone({bindingTicket, phone, challengeId, code}) {
    const payload = await this.request(
      "/v1/auth/wecom/bind-phone",
      {
        method: "POST",
        body: JSON.stringify({
          binding_ticket: bindingTicket,
          phone,
          sms_challenge_id: challengeId,
          sms_code: code,
        }),
      },
      {auth: false},
    );
    return this.setSession(payload);
  }

  async logout() {
    try {
      if (this.session?.access_token) {
        await this.request("/v1/auth/logout", {method: "POST"}, {retry: true});
      }
    } finally {
      this.clearSession();
    }
  }
}

export const authStorageKeys = {session: SESSION_KEY, device: DEVICE_KEY};
