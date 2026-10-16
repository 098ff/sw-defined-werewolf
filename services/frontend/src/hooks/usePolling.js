import { useEffect, useRef, useState } from 'react';

export const POLL_INTERVAL_MS = 2000;
const BACKOFF_STEP_MS = 1000;
const BACKOFF_CAP_MS = 5000;
const JITTER_MS = 300;

// Failure n (1-based) waits 2s → 3s → 4s → 5s (capped), ± jitter.
export function backoffDelay(failures) {
  if (failures <= 0) return POLL_INTERVAL_MS;
  const base = Math.min(POLL_INTERVAL_MS + (failures - 1) * BACKOFF_STEP_MS, BACKOFF_CAP_MS);
  return base + Math.round((Math.random() * 2 - 1) * JITTER_MS);
}

/**
 * Plain REST polling (no WebSockets / SSE / long-poll).
 * `poll` is an async fn returning the api() result. Uses a setTimeout chain so requests never overlap.
 * Returns { syncing } — true while the last poll failed and we're retrying with backoff.
 */
export function usePolling(poll, { enabled = true, deps = [] } = {}) {
  const pollRef = useRef(poll);
  pollRef.current = poll;
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let timer;
    let failures = 0;

    const tick = async () => {
      let ok = false;
      try {
        const res = await pollRef.current();
        // Client errors (4xx) are a definitive answer, not a transient outage.
        ok = Boolean(res?.ok) || (res?.status >= 400 && res?.status < 500);
      } catch {
        ok = false;
      }
      if (cancelled) return;
      failures = ok ? 0 : failures + 1;
      setSyncing(!ok);
      timer = setTimeout(tick, backoffDelay(failures));
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  return { syncing };
}
