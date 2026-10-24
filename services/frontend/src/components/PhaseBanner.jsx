import { Moon, Sun, Timer, Trophy } from 'lucide-react';
import { useCountdown } from '../hooks/useCountdown';

const PHASES = {
  NIGHT: { icon: Moon, label: 'Night', iconTone: 'text-indigo-200' },
  DAY: { icon: Sun, label: 'Day', iconTone: 'text-amber-600' },
  ENDED: { icon: Trophy, label: 'Game over', iconTone: 'text-amber-300' }
};

export default function PhaseBanner({ state }) {
  const ended = state.phase === 'ENDED';
  const left = useCountdown(ended ? null : state.phase_end_time);
  const phase = PHASES[state.phase] ?? { icon: Timer, label: state.phase, iconTone: 'text-muted' };
  const Icon = phase.icon;
  const time = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;

  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-panel/70 px-4 py-3">
      <Icon className={`h-8 w-8 shrink-0 ${phase.iconTone}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="text-lg font-bold leading-tight">
          {phase.label} {!ended && state.day_count ? state.day_count : ''}
        </div>
        {state.announcement && <p className="text-sm text-muted">{state.announcement}</p>}
      </div>
      {!ended && (
        <div
          className={`shrink-0 rounded-lg border border-line px-3 py-1 font-mono text-2xl tabular-nums ${left <= 10 ? 'text-bad' : ''}`}
          aria-label="Time left"
        >
          {left > 0 ? time : '…'}
        </div>
      )}
    </div>
  );
}
