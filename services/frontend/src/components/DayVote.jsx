import { useEffect, useState } from 'react';
import { Check, Gavel } from 'lucide-react';
import { gameApi } from '../api/client';
import TargetPicker from './TargetPicker';

const SKIP = 'SKIP';

export default function DayVote({ session, state }) {
  const { me, players, phase_version: phaseVersion } = state;
  const [choice, setChoice] = useState(null);
  const [cast, setCast] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setChoice(null);
    setCast(null);
    setError(null);
  }, [phaseVersion]);

  if (!me.alive) {
    return <div className="card text-sm text-slate-400">The dead cannot vote. Watch the village decide.</div>;
  }

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await gameApi.vote(session.room_id, session.player_token, { phase_version: phaseVersion, target_id: choice });
    setBusy(false);
    if (res.ok) setCast(choice);
    else setError(res.error?.message || res.error?.code);
  };

  const locked = cast !== null;
  const candidates = players.filter((p) => p.alive && p.player_id !== me.player_id);
  const castLabel = cast === SKIP ? 'Skip' : players.find((p) => p.player_id === cast)?.name;

  return (
    <div className="card">
      <h3 className="mb-3 flex items-center gap-2 font-semibold">
        <Gavel className="h-4 w-4" /> Who should be executed?
      </h3>
      <TargetPicker
        name="day-vote"
        candidates={[...candidates, { player_id: SKIP, label: 'Skip Vote' }]}
        value={locked ? cast : choice}
        onChange={setChoice}
        disabled={locked}
      />
      <div className="mt-3 flex items-center gap-3">
        <button type="button" className="btn-primary" disabled={!choice || locked || busy} onClick={submit}>
          Cast vote
        </button>
        {locked && (
          <span className="flex items-center gap-1 text-sm text-emerald-300">
            <Check className="h-4 w-4" /> Voted: {castLabel}
          </span>
        )}
      </div>
      {error && <p className="mt-2 text-sm text-rose-400">{error}</p>}
    </div>
  );
}
