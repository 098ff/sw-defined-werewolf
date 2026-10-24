import { useState } from 'react';
import { Eye, EyeOff, Skull } from 'lucide-react';
import { ROLE_INFO } from '../api/roles';
import RoleArt from './RoleArt';

const HIDE_KEY = 'werewolf.roleHidden';

function readHidden() {
  try {
    return sessionStorage.getItem(HIDE_KEY) === '1';
  } catch {
    return false;
  }
}

// Private role card. Shown by default; the eye button hides it if someone is looking over your shoulder.
export default function RoleCard({ me, players }) {
  const [hidden, setHidden] = useState(readHidden);
  const info = ROLE_INFO[me.role];
  const packmates = me.role === 'WEREWOLF' ? players.filter((p) => p.role === 'WEREWOLF' && p.player_id !== me.player_id) : [];
  const seer = me.private_info?.seer_result;
  const seerTarget = seer && players.find((p) => p.player_id === seer.target_id);

  const toggle = () => {
    setHidden((h) => {
      try {
        sessionStorage.setItem(HIDE_KEY, h ? '0' : '1');
      } catch {
        /* ignore */
      }
      return !h;
    });
  };

  return (
    <div className="relative flex flex-col items-center rounded-xl border border-line bg-panel/80 p-4 text-center sm:w-44 sm:shrink-0">
      <button type="button" onClick={toggle} className="absolute right-2 top-2 rounded p-1 text-muted hover:text-ink">
        {hidden ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
        <span className="sr-only">{hidden ? 'Show my role' : 'Hide my role'}</span>
      </button>
      <RoleArt role={hidden ? null : me.role} size={72} className={me.alive ? '' : 'opacity-50 grayscale'} />
      {hidden ? (
        <>
          <div className="mt-2 font-bold">Role hidden</div>
          <div className="text-xs text-muted">Tap the eye to show</div>
        </>
      ) : (
        <>
          <div className="mt-2 text-lg font-bold">{info?.label ?? me.role}</div>
          <div className="text-xs uppercase tracking-wide text-muted">Team {info?.alignment?.toLowerCase()}</div>
          {!me.alive && (
            <div className="mt-1 flex items-center gap-1 text-xs text-muted">
              <Skull className="h-3 w-3" /> eliminated
            </div>
          )}
          {packmates.length > 0 && <div className="mt-2 text-xs text-bad">Pack: {packmates.map((p) => p.name).join(', ')}</div>}
          {seer && (
            <div className="mt-2 text-xs">
              Vision: <strong>{seerTarget?.name ?? seer.target_id}</strong>{' '}
              <strong className={seer.result === 'WEREWOLF' ? 'text-bad' : 'text-good'}>
                {seer.result === 'WEREWOLF' ? 'is a werewolf' : 'is good'}
              </strong>
            </div>
          )}
        </>
      )}
    </div>
  );
}
