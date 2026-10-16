import { useState } from 'react';
import { Activity, ChevronDown, ChevronUp, Network } from 'lucide-react';
import { useTraceStore, verifyTrace } from '../api/traceStore';

const STATUS_TONE = {
  ok: 'text-emerald-300 border-emerald-500/40',
  same: 'text-amber-300 border-amber-500/40',
  partial: 'text-amber-300 border-amber-500/40',
  none: 'text-slate-400 border-slate-700'
};

const COLLAPSE_KEY = 'werewolf.traceHudOpen';

function readOpen() {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

function pathSummary(trace) {
  if (!trace?.length) return 'awaiting first request…';
  return trace.map((h) => `${h.service} (${h.node})`).join(' ➔ ');
}

export default function TraceHUD() {
  const { latest, history } = useTraceStore();
  const [open, setOpen] = useState(readOpen);
  const verdict = verifyTrace(latest?.trace);

  const toggle = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, o ? '0' : '1');
      } catch {
        /* ignore */
      }
      return !o;
    });
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 flex justify-center px-3 pb-3 pointer-events-none">
      <div
        className={`pointer-events-auto w-full max-w-3xl rounded-xl border bg-slate-950/95 shadow-2xl backdrop-blur ${STATUS_TONE[verdict.status]}`}
      >
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="flex w-full items-center gap-2 px-3 py-2 text-left font-mono text-xs"
        >
          <Network className="h-4 w-4 shrink-0" />
          <span className="truncate text-slate-200">
            Path: {pathSummary(latest?.trace)}
            <span className="text-slate-500"> | </span>
            Trace verified: <span className="font-semibold">{verdict.label}</span>
          </span>
          <span className="ml-auto shrink-0 text-slate-500">
            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </span>
        </button>

        {open && (
          <div className="max-h-72 overflow-y-auto border-t border-slate-800 px-3 py-2 font-mono text-[11px] text-slate-300">
            {latest && (
              <div className="mb-3 space-y-1">
                <div>
                  <span className="text-slate-500">request_id:</span> {latest.request_id ?? '—'}
                  <span className="text-slate-500"> · </span>
                  {latest.method} {latest.path}
                  <span className="text-slate-500"> · </span>
                  HTTP {latest.status || 'ERR'} · {latest.latency_ms}ms
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  {latest.trace.map((hop, i) => (
                    <span key={i} className="flex items-center gap-1">
                      <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5">
                        <span className="font-semibold text-slate-100">{hop.service}</span>{' '}
                        <span className="text-slate-500">{hop.pod}</span> @{' '}
                        <span className="text-sky-300">{hop.node}</span>
                      </span>
                      {i < latest.trace.length - 1 && <span className="text-slate-500">➔</span>}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="mb-1 flex items-center gap-1 text-slate-500">
              <Activity className="h-3 w-3" /> Recent requests
            </div>
            <table className="w-full">
              <tbody>
                {history.map((h) => {
                  const v = verifyTrace(h.trace);
                  return (
                    <tr key={`${h.at}-${h.request_id}`} className="border-t border-slate-900">
                      <td className="py-0.5 pr-2 text-slate-500">{new Date(h.at).toLocaleTimeString()}</td>
                      <td className={`pr-2 ${h.ok ? 'text-emerald-400' : 'text-rose-400'}`}>{h.status || 'ERR'}</td>
                      <td className="pr-2">
                        {h.method} {h.path}
                      </td>
                      <td className="pr-2 text-slate-400">{h.trace.map((t) => t.node).join(' ➔ ') || '—'}</td>
                      <td className={v.status === 'ok' ? 'text-emerald-400' : 'text-amber-400'}>{v.label}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
