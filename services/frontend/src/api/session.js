// player_token + room_id live in sessionStorage so a browser refresh keeps the game session.
const KEY = 'werewolf.session';

export function loadSession() {
  try {
    const raw = sessionStorage.getItem(KEY);
    const s = raw ? JSON.parse(raw) : null;
    return s?.player_token && s?.room_id ? s : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    /* storage unavailable: session survives only until refresh */
  }
}

export function clearSession() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
