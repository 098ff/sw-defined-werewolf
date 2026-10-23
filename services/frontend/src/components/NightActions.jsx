import { useEffect, useState } from 'react';
import { BedDouble, Check, Eye, ShieldPlus, Swords } from 'lucide-react';
import { gameApi } from '../api/client';
import { NIGHT_ACTIONS } from '../api/roles';
import TargetPicker from './TargetPicker';

const COPY = {
  WEREWOLF: { icon: Swords, title: 'Choose your victim', button: 'Attack' },
  DOCTOR: { icon: ShieldPlus, title: 'Choose someone to protect', button: 'Protect' },
  SEER: { icon: Eye, title: 'Choose someone to inspect', button: 'Inspect' }
};

function candidatesFor(role, me, players) {
  const living = players.filter((p) => p.alive);
  if (role === 'DOCTOR') return living; // Doctor may protect themselves.
  return living.filter((p) => p.player_id !== me.player_id);
}

export default function NightActions({ session, state }) {
  const { me, players, phase_version: phaseVersion } = state;
  const [target, setTarget] = useState(null);
  const [submitted, setSubmitted] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Fresh selection each night.
  useEffect(() => {
    setTarget(null);
    setSubmitted(null);
    setError(null);
  }, [phaseVersion]);

  const copy = COPY[me.role];
  if (!me.alive) return null;
  if (!copy) {
    return (
      <div className="card flex flex-col items-center py-8 text-center text-slate-400">
        <BedDouble className="mb-2 h-8 w-8 text-indigo-300" />
        <p className="font-medium text-slate-200">You are fast asleep…</p>
        <p className="text-sm">Villagers have no night action. Wait for sunrise.</p>
      </div>
    );
  }

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await gameApi.nightAction(session.room_id, session.player_token, {
      phase_version: phaseVersion,
      action: NIGHT_ACTIONS[me.role],
      target_id: target
    });
    setBusy(false);
    if (res.ok) setSubmitted(target);
    else setError(res.error?.message || res.error?.code);
  };

  const Icon = copy.icon;
  const locked = submitted !== null;
  const lockedName = players.find((p) => p.player_id === submitted)?.name;

  return (
    <div className="card">
      <h3 className="mb-3 flex items-center gap-2 font-semibold">
        <Icon className="h-4 w-4" /> {copy.title}
      </h3>
      <TargetPicker name="night-target" candidates={candidatesFor(me.role, me, players)} value={locked ? submitted : target} onChange={setTarget} disabled={locked} />
      <div className="mt-3 flex items-center gap-3">
        <button type="button" className="btn-primary" disabled={!target || locked || busy} onClick={submit}>
          {copy.button}
        </button>
        {locked && (
          <span className="flex items-center gap-1 text-sm text-emerald-300">
            <Check className="h-4 w-4" /> Locked in: {lockedName}
          </span>
        )}
      </div>
      {error && <p className="mt-2 text-sm text-rose-400">{error}</p>}
    </div>
  );
}
