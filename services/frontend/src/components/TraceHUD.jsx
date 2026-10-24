import { useState } from 'react';
import { Route, X } from 'lucide-react';
import { useLatestTrace, verifyTrace } from '../api/traceStore';

const OPEN_KEY = 'werewolf.traceHudOpen';

function readOpen() {
  try {
    return localStorage.getItem(OPEN_KEY) === '1';
  } catch {
    return false;
  }
}

const DOT = { ok: 'bg-emerald-400', same: 'bg-amber-400', partial: 'bg-amber-400', none: 'bg-slate-500' };

// System Trace HUD: hidden behind a small pill by default; one tap shows the live
// cross-node path for the demo (`gateway (pi-01) ➔ gamemaster (pi-04) | Trace verified: Cross-Node OK`).
export default function TraceHUD() {
  const latest = useLatestTrace();
  const [open, setOpen] = useState(readOpen);
  const verdict = verifyTrace(latest?.trace);

  const toggle = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(OPEN_KEY, o ? '0' : '1');
      } catch {
        /* ignore */
      }
      return !o;
    });
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={toggle}
        className="fixed bottom-4 left-4 z-30 flex items-center gap-2 rounded-full border border-line bg-panel/90 px-3 py-1.5 text-xs text-muted shadow backdrop-blur hover:text-ink"
      >
        <Route className="h-3.5 w-3.5" />
        <span className={`h-2 w-2 rounded-full ${DOT[verdict.status]}`} aria-hidden="true" />
        Trace hidden. Tap to show
      </button>
    );
  }

  const path = latest?.trace?.length ? latest.trace.map((h) => `${h.service} (${h.node})`).join(' ➔ ') : 'awaiting first request…';

  return (
    <div className="fixed bottom-4 left-4 right-4 z-30 mx-auto max-w-2xl rounded-xl border border-line bg-panel/95 px-3 py-2 font-mono text-xs shadow-xl backdrop-blur md:right-auto">
      <div className="flex items-start gap-2">
        <Route className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <div className="break-words">
            Path: {path}
            <span className="text-muted"> | </span>
            Trace verified: <span className={`font-semibold ${verdict.status === 'ok' ? 'text-good' : 'text-bad'}`}>{verdict.label}</span>
          </div>
          {latest && (
            <div className="mt-1 text-muted">
              {latest.request_id ?? '—'} · {latest.method} {latest.path} · HTTP {latest.status || 'ERR'} · {latest.latency_ms}ms
            </div>
          )}
          {latest?.trace?.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {latest.trace.map((hop, i) => (
                <span key={i} className="rounded border border-line bg-sunken/70 px-1.5 py-0.5">
                  {hop.service} <span className="text-muted">{hop.pod}</span> @ <span className="text-accent">{hop.node}</span>
                </span>
              ))}
            </div>
          )}
        </div>
        <button type="button" onClick={toggle} className="rounded p-0.5 text-muted hover:text-ink" aria-label="Hide trace">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
