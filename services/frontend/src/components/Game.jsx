import { useEffect, useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { gameApi, isSessionGone } from '../api/client';
import { useMediaQuery } from '../hooks/useMediaQuery';
import { usePolling } from '../hooks/usePolling';
import ChatPanel from './ChatPanel';
import GameOverModal from './GameOverModal';
import PhaseBanner from './PhaseBanner';
import PlayerGrid from './PlayerGrid';
import RoleCard from './RoleCard';
import SkyBackdrop from './SkyBackdrop';
import SyncBadge from './SyncBadge';
import YourMove from './YourMove';

const THEMES = { NIGHT: 'night', DAY: 'day' };

// Swap the page palette (CSS variables in index.css) to match the current phase.
function usePhaseTheme(phase) {
  useEffect(() => {
    const root = document.documentElement;
    const theme = THEMES[phase];
    if (theme) root.dataset.theme = theme;
    else delete root.dataset.theme;
  }, [phase]);
  useEffect(() => () => delete document.documentElement.dataset.theme, []);
}

export default function Game({ session, onExit }) {
  const [state, setState] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const desktop = useMediaQuery('(min-width: 768px)');

  const { syncing } = usePolling(
    async () => {
      const res = await gameApi.state(session.room_id, session.player_token);
      if (res.ok) setState(res.data);
      else if (isSessionGone(res)) onExit(res.error?.message);
      return res;
    },
    { deps: [session.room_id, session.player_token] }
  );

  usePhaseTheme(state?.phase);

  if (!state) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-muted">
        <SyncBadge syncing={syncing} />
        Gathering the village…
      </div>
    );
  }

  return (
    <>
      <SkyBackdrop phase={state.phase} />
      <SyncBadge syncing={syncing} />
      <div className="mx-auto max-w-6xl px-4 pb-16 pt-4 md:grid md:grid-cols-[minmax(0,1fr)_20rem] md:gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <main className="space-y-4">
          <PhaseBanner state={state} />
          <div className="flex flex-col gap-4 sm:flex-row sm:items-stretch">
            <RoleCard me={state.me} players={state.players} />
            <YourMove session={session} state={state} />
          </div>
          <PlayerGrid players={state.players} meId={state.me.player_id} />
        </main>

        {/* Single ChatPanel instance: pinned right column on tablet/desktop, slide-out drawer on phones. */}
        <aside
          className={`fixed inset-y-0 right-0 z-40 w-[88vw] max-w-sm p-3 transition-transform duration-300 md:sticky md:top-4 md:z-auto md:h-[calc(100vh-5rem)] md:w-auto md:max-w-none md:translate-x-0 md:p-0 ${
            chatOpen ? 'translate-x-0 bg-page shadow-2xl' : 'translate-x-full'
          }`}
          aria-label="Chat"
        >
          <ChatPanel
            session={session}
            state={state}
            visible={desktop || chatOpen}
            onUnreadChange={setUnread}
            onClose={() => setChatOpen(false)}
          />
        </aside>
      </div>

      {!chatOpen && (
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          className="btn-primary fixed bottom-4 right-4 z-30 rounded-full shadow-lg md:hidden"
        >
          <MessageSquare className="h-4 w-4" /> Chat
          {unread > 0 && <span className="rounded-full bg-on-accent px-1.5 text-xs text-accent">{unread}</span>}
        </button>
      )}
      {chatOpen && <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setChatOpen(false)} aria-hidden="true" />}

      {state.phase === 'ENDED' && <GameOverModal state={state} onExit={() => onExit()} />}
    </>
  );
}
