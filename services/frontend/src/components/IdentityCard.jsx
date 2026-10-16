import { useState } from 'react';
import { Eye, EyeOff, Skull } from 'lucide-react';
import { ROLE_INFO } from '../api/roles';

// Private role banner. Starts hidden so a neighbour can't glance at the screen.
export default function IdentityCard({ me, players }) {
  const [revealed, setRevealed] = useState(false);
  const info = ROLE_INFO[me.role];
  const packmates = me.role === 'WEREWOLF' ? players.filter((p) => p.role === 'WEREWOLF' && p.player_id !== me.player_id) : [];
  const seer = me.private_info?.seer_result;
  const seerTarget = seer && players.find((p) => p.player_id === seer.target_id);

  return (
    <div className={`rounded-xl border p-4 ${revealed && info ? info.tone : 'border-slate-800 bg-slate-900/70'}`}>
      <div className="flex items-center gap-2">
        <span className="label mb-0">My role</span>
        {!me.alive && (
          <span className="flex items-center gap-1 text-xs text-slate-400">
            <Skull className="h-3 w-3" /> eliminated
          </span>
        )}
        <button type="button" className="ml-auto text-slate-400 hover:text-slate-200" onClick={() => setRevealed((r) => !r)}>
          {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          <span className="sr-only">{revealed ? 'Hide role' : 'Reveal role'}</span>
        </button>
      </div>
      {revealed ? (
        <div className="mt-2">
          <div className="text-2xl font-bold">{info?.label ?? me.role}</div>
          <div className="text-xs uppercase tracking-wide opacity-80">Team: {info?.alignment}</div>
          <p className="mt-2 text-sm opacity-90">{info?.description}</p>
          {packmates.length > 0 && <p className="mt-2 text-sm">Your pack: {packmates.map((p) => p.name).join(', ')}</p>}
          {seer && (
            <p className="mt-2 text-sm">
              Vision: <strong>{seerTarget?.name ?? seer.target_id}</strong> is{' '}
              <strong className={seer.result === 'WEREWOLF' ? 'text-rose-300' : 'text-emerald-300'}>
                {seer.result === 'WEREWOLF' ? 'a Werewolf' : 'Good'}
              </strong>
              .
            </p>
          )}
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-500">Tap the eye to reveal. Keep it secret.</p>
      )}
    </div>
  );
}
