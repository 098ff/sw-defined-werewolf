// Tiny external store feeding the System Trace HUD with the latest gateway response.
import { useSyncExternalStore } from 'react';

let latest = null;
const listeners = new Set();

export function recordTrace(entry) {
  latest = entry;
  listeners.forEach((l) => l());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLatestTrace() {
  return useSyncExternalStore(subscribe, () => latest);
}

// SDN validation rule (api-contract §1.2): trace[0] (gateway) and trace[1] (handler) on different nodes.
export function verifyTrace(trace) {
  if (!Array.isArray(trace) || trace.length === 0) return { status: 'none', label: 'No trace' };
  if (trace.length < 2) return { status: 'partial', label: 'Handler hop missing' };
  return trace[0].node !== trace[1].node
    ? { status: 'ok', label: 'Cross-Node OK' }
    : { status: 'same', label: 'Same-Node (not cross-node)' };
}
