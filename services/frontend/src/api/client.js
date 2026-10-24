// Thin fetch wrapper around the gateway's standard envelope:
//   { ok, data | error, request_id, trace }
// Never throws: network failures come back as { ok: false, status: 0 }.
import { recordTrace } from './traceStore';

const REQUEST_TIMEOUT_MS = 6000;

// Server-minus-client clock offset (ms). Lets countdowns track the server-authoritative
// phase_end_time even if the client clock drifts. Preferred source is the GameMaster's
// `server_time` (Redis TIME, same clock as phase_end_time); the gateway Date header is a fallback.
let clockOffsetMs = 0;
let haveServerTime = false;
export const serverNow = () => Date.now() + clockOffsetMs;

export function syncServerTime(serverTimeSec, sentAt) {
  if (typeof serverTimeSec !== 'number' || serverTimeSec <= 0) return;
  const midpoint = sentAt + (Date.now() - sentAt) / 2;
  clockOffsetMs = serverTimeSec * 1000 - midpoint;
  haveServerTime = true;
}

function learnClockOffset(res, sentAt) {
  if (haveServerTime) return;
  const header = res.headers.get('date');
  if (!header) return;
  const server = Date.parse(header);
  if (Number.isNaN(server)) return;
  const midpoint = sentAt + (Date.now() - sentAt) / 2;
  // Date header has 1s resolution; only correct meaningful drift.
  const offset = server - midpoint;
  clockOffsetMs = Math.abs(offset) > 1500 ? offset : 0;
}

export async function api(path, { method = 'GET', body, token } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const sentAt = Date.now();

  let result;
  try {
    const res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal
    });
    learnClockOffset(res, sentAt);
    let json = null;
    try {
      json = await res.json();
    } catch {
      /* non-JSON body */
    }
    if (json?.ok) syncServerTime(json.data?.server_time, sentAt);
    result = {
      ok: Boolean(json?.ok) && res.ok,
      status: res.status,
      data: json?.data ?? null,
      error: json?.error ?? (res.ok ? null : { code: `HTTP_${res.status}`, message: res.statusText }),
      request_id: json?.request_id ?? res.headers.get('x-request-id'),
      trace: Array.isArray(json?.trace) ? json.trace : []
    };
  } catch (err) {
    const timedOut = err?.name === 'AbortError';
    result = {
      ok: false,
      status: 0,
      data: null,
      error: { code: timedOut ? 'TIMEOUT' : 'NETWORK_ERROR', message: timedOut ? 'Request timed out' : 'Gateway unreachable' },
      request_id: null,
      trace: []
    };
  } finally {
    clearTimeout(timer);
  }

  recordTrace({
    method,
    path: path.split('?')[0],
    status: result.status,
    ok: result.ok,
    request_id: result.request_id,
    trace: result.trace,
    latency_ms: Date.now() - sentAt,
    at: Date.now()
  });
  return result;
}

export const lobbyApi = {
  create: (name) => api('/api/lobby/rooms', { method: 'POST', body: { name } }),
  join: (roomId, name) => api(`/api/lobby/rooms/${encodeURIComponent(roomId)}/join`, { method: 'POST', body: { name } }),
  get: (roomId, token) => api(`/api/lobby/rooms/${encodeURIComponent(roomId)}`, { token }),
  start: (roomId, token) => api(`/api/lobby/rooms/${encodeURIComponent(roomId)}/start`, { method: 'POST', token }),
  // Contract §5.1: removes the caller from a WAITING room (host passes on); 409 once the game has started.
  leave: (roomId, token) => api(`/api/lobby/rooms/${encodeURIComponent(roomId)}/leave`, { method: 'POST', token })
};

export const gameApi = {
  state: (roomId, token) => api(`/api/game/rooms/${encodeURIComponent(roomId)}/state`, { token }),
  nightAction: (roomId, token, body) =>
    api(`/api/game/rooms/${encodeURIComponent(roomId)}/night-actions`, { method: 'POST', body, token }),
  vote: (roomId, token, body) => api(`/api/game/rooms/${encodeURIComponent(roomId)}/vote`, { method: 'POST', body, token })
};

export const chatApi = {
  list: (roomId, token, afterId) =>
    api(`/api/chat/rooms/${encodeURIComponent(roomId)}/messages?after_id=${afterId}`, { token }),
  send: (roomId, token, channel, text) =>
    api(`/api/chat/rooms/${encodeURIComponent(roomId)}/messages`, { method: 'POST', body: { channel, text }, token })
};

// Errors that mean the stored session is dead (e.g. Redis reset) and the user must start over.
export const isSessionGone = (res) =>
  res.status === 401 || (res.status === 404 && res.error?.code === 'ROOM_NOT_FOUND');
