import { useState } from 'react';
import { gameApi, isSessionGone } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import ChatPanel from './ChatPanel';
import DayVote from './DayVote';
import GameOverModal from './GameOverModal';
import IdentityCard from './IdentityCard';
import NightActions from './NightActions';
import PhaseBanner from './PhaseBanner';
import PlayerGrid from './PlayerGrid';
import SyncBadge from './SyncBadge';

export default function Game({ session, onExit }) {
  const [state, setState] = useState(null);

  const { syncing } = usePolling(
    async () => {
      const res = await gameApi.state(session.room_id, session.player_token);
      if (res.ok) setState(res.data);
      else if (isSessionGone(res)) onExit(res.error?.message);
      return res;
    },
    { deps: [session.room_id, session.player_token] }
  );

  if (!state) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-slate-400">
        <SyncBadge syncing={syncing} />
        Gathering the village…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 pb-24 pt-6">
      <SyncBadge syncing={syncing} />
      <PhaseBanner state={state} />
      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <IdentityCard me={state.me} players={state.players} />
          {state.phase === 'NIGHT' && <NightActions session={session} state={state} />}
          {state.phase === 'DAY' && <DayVote session={session} state={state} />}
          <PlayerGrid players={state.players} meId={state.me.player_id} />
        </div>
        <ChatPanel session={session} state={state} />
      </div>
      {state.phase === 'ENDED' && <GameOverModal state={state} onExit={() => onExit()} />}
    </div>
  );
}
