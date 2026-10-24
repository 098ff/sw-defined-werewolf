import { useEffect, useState } from 'react';
import { BedDouble, Check, Eye, Gavel, Ghost, ShieldPlus, Swords } from 'lucide-react';
import { gameApi } from '../api/client';
import { NIGHT_ACTIONS } from '../api/roles';
import TargetPicker from './TargetPicker';

const SKIP = 'SKIP';

const NIGHT_MOVES = {
  WEREWOLF: {
    icon: Swords,
    title: 'Choose who to attack tonight',
    hint: "Tap a player, then confirm. You can't change it after confirming.",
    button: 'Confirm attack',
    selfAllowed: false
  },
  DOCTOR: {
    icon: ShieldPlus,
    title: 'Choose someone to protect',
    hint: 'You can pick yourself. If the werewolves attack that player tonight, they survive.',
    button: 'Confirm protection',
    selfAllowed: true
  },
  SEER: {
    icon: Eye,
    title: 'Choose someone to investigate',
    hint: "You'll learn whether they're a werewolf. Only you see the result.",
    button: 'Confirm investigation',
    selfAllowed: false
  }
};

function describeMove(me, phase, players) {
  if (!me.alive) {
    return { icon: Ghost, title: "You're out of the game", hint: 'Watch how it plays out. You can talk with other fallen players in Dead chat.' };
  }
  if (phase === 'NIGHT') {
    const move = NIGHT_MOVES[me.role];
    if (!move) return { icon: BedDouble, title: "You're asleep", hint: 'Villagers have no night action. Wait for morning.' };
    const hasPack = me.role === 'WEREWOLF' && players.some((p) => p.role === 'WEREWOLF' && p.player_id !== me.player_id);
    return { ...move, kind: 'night', hint: hasPack ? `${move.hint} Plan with your pack in Wolf chat.` : move.hint };
  }
  if (phase === 'DAY') {
    return {
      icon: Gavel,
      title: 'Discuss, then vote someone out',
      hint: 'Share what you know in Public chat. Pick one player or skip. Voting closes once everyone has voted or the timer runs out.',
      button: 'Cast vote',
      kind: 'vote'
    };
  }
  return null;
}

function candidatesFor(move, me, players) {
  const living = players.filter((p) => p.alive);
  if (move.kind === 'vote') {
    return [...living.filter((p) => p.player_id !== me.player_id), { player_id: SKIP, label: 'Skip vote', dashed: true }];
  }
  return move.selfAllowed ? living : living.filter((p) => p.player_id !== me.player_id);
}

// One card that tells the player exactly what to do right now, with the controls to do it.
export default function YourMove({ session, state }) {
  const { me, players, phase, phase_version: phaseVersion } = state;
  const [choice, setChoice] = useState(null);
  const [locked, setLocked] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Fresh choice every phase.
  useEffect(() => {
    setChoice(null);
    setLocked(null);
    setError(null);
  }, [phaseVersion]);

  const move = describeMove(me, phase, players);
  if (!move) return null;

  const nameOf = (id) => (id === SKIP ? 'Skip' : players.find((p) => p.player_id === id)?.name ?? id);
  const isLocked = locked !== null;
  const Icon = isLocked ? Check : move.icon;
  const title = isLocked ? `${move.kind === 'vote' ? 'Vote cast' : 'Locked in'}: ${nameOf(locked)}` : move.title;
  const hint = isLocked
    ? move.kind === 'vote'
      ? 'Waiting for the others. Day ends once everyone has voted.'
      : 'Waiting for the other players…'
    : move.hint;

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res =
      move.kind === 'vote'
        ? await gameApi.vote(session.room_id, session.player_token, { phase_version: phaseVersion, target_id: choice })
        : await gameApi.nightAction(session.room_id, session.player_token, {
            phase_version: phaseVersion,
            action: NIGHT_ACTIONS[me.role],
            target_id: choice
          });
    setBusy(false);
    if (res.ok) setLocked(choice);
    // The phase can move on mid-click now that day and night both end early; the next poll catches up.
    else if (res.error?.code === 'PHASE_VERSION_CONFLICT') setError('The phase just changed. Updating…');
    else setError(res.error?.message || res.error?.code);
  };

  return (
    <section className="min-w-0 flex-1 rounded-xl bg-move p-4 text-move-ink shadow-sm" aria-labelledby="your-move-title">
      <div className="text-xs font-semibold uppercase tracking-wide text-move-muted">Your move</div>
      <h2 id="your-move-title" className="mt-1 flex items-center gap-2 text-xl font-bold">
        <Icon className="h-5 w-5 shrink-0" aria-hidden="true" /> {title}
      </h2>
      <p className="mt-1 text-sm text-move-muted">{hint}</p>

      {move.kind && (
        <>
          <div className="mt-4">
            <TargetPicker
              name={`move-${move.kind}`}
              candidates={candidatesFor(move, me, players)}
              value={isLocked ? locked : choice}
              onChange={setChoice}
              disabled={isLocked}
            />
          </div>
          {!isLocked && (
            <button type="button" className="btn-primary mt-4" disabled={!choice || busy} onClick={submit}>
              {busy ? 'Sending…' : move.button}
            </button>
          )}
          {error && <p className="mt-2 text-sm font-medium text-red-700">{error}</p>}
        </>
      )}
    </section>
  );
}
