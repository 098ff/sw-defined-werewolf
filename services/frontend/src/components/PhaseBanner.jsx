import { Moon, Sun, Timer, Trophy } from 'lucide-react';
import { useCountdown } from '../hooks/useCountdown';

const PHASES = {
  NIGHT: { icon: Moon, label: 'Night', tone: 'from-indigo-950 to-slate-900 border-indigo-800 text-indigo-200' },
  DAY: { icon: Sun, label: 'Day', tone: 'from-amber-900/60 to-slate-900 border-amber-700 text-amber-100' },
  ENDED: { icon: Trophy, label: 'Game Over', tone: 'from-slate-800 to-slate-900 border-slate-700 text-slate-100' }
};

export default function PhaseBanner({ state }) {
  const left = useCountdown(state.phase === 'ENDED' ? null : state.phase_end_time);
  const phase = PHASES[state.phase] ?? { icon: Timer, label: state.phase, tone: 'from-slate-800 to-slate-900 border-slate-700' };
  const Icon = phase.icon;
  const mm = String(Math.floor(left / 60)).padStart(1, '0');
  const ss = String(left % 60).padStart(2, '0');

  return (
    <div className={`rounded-xl border bg-gradient-to-r p-4 ${phase.tone}`}>
      <div className="flex items-center gap-3">
        <Icon className="h-7 w-7" />
        <div>
          <div className="text-xl font-bold">
            {phase.label} {state.phase !== 'ENDED' && state.day_count ? state.day_count : ''}
          </div>
          <div className="text-xs opacity-70">Room {state.room_id}</div>
        </div>
        {state.phase !== 'ENDED' && (
          <div className={`ml-auto font-mono text-3xl tabular-nums ${left <= 10 ? 'text-rose-300' : ''}`} aria-label="Time left">
            {left > 0 ? `${mm}:${ss}` : 'resolving…'}
          </div>
        )}
      </div>
      {state.announcement && <p className="mt-3 text-sm opacity-90">{state.announcement}</p>}
    </div>
  );
}
