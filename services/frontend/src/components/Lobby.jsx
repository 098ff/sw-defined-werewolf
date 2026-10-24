import { useRef, useState } from 'react';
import { Check, Copy, Crown, LogOut, Play, Users } from 'lucide-react';
import { copyText, selectText } from '../utils/clipboard';
import { isSessionGone, lobbyApi } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import SyncBadge from './SyncBadge';

const MIN_PLAYERS = 4;
const MAX_PLAYERS = 6;

export default function Lobby({ session, onStarted, onLeave }) {
  const [lobby, setLobby] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [copyState, setCopyState] = useState(null); // 'copied' | 'manual' | null
  const [leaving, setLeaving] = useState(false);
  const codeRef = useRef(null);

  const { syncing } = usePolling(
    async () => {
      const res = await lobbyApi.get(session.room_id, session.player_token);
      if (res.ok) {
        setLobby(res.data);
        if (res.data.phase && res.data.phase !== 'WAITING') onStarted();
      } else if (isSessionGone(res)) {
        onLeave(res.error?.message);
      }
      return res;
    },
    { deps: [session.room_id, session.player_token] }
  );

  const players = lobby?.players ?? [];
  const isHost = lobby ? lobby.host_player_id === session.player_id : session.is_host;
  const canStart = isHost && players.length >= MIN_PLAYERS && players.length <= MAX_PLAYERS;

  const start = async () => {
    setStarting(true);
    setError(null);
    const res = await lobbyApi.start(session.room_id, session.player_token);
    setStarting(false);
    if (res.ok) onStarted();
    else setError(res.error?.message || res.error?.code);
  };

  const copyCode = async () => {
    const ok = await copyText(session.room_id);
    if (!ok) selectText(codeRef.current);
    setCopyState(ok ? 'copied' : 'manual');
    setTimeout(() => setCopyState(null), 2500);
  };

  // Tell the Lobby we're gone so other players stop seeing us.
  const leave = async () => {
    setLeaving(true);
    setError(null);
    const res = await lobbyApi.leave(session.room_id, session.player_token);
    if (res.ok || res.status === 401 || res.status === 404) {
      // Left, or there's nothing left to leave (token already revoked / room gone).
      onLeave();
    } else if (res.error?.code === 'GAME_ALREADY_STARTED') {
      // Too late to leave: roles are assigned, so take the player into the game instead.
      onStarted();
    } else {
      // Network or server trouble: keep the session so the player can retry instead of lingering as a ghost.
      setLeaving(false);
      setError("Couldn't leave right now. Try again.");
    }
  };

  return (
    <div className="mx-auto max-w-xl px-4 pt-10">
      <SyncBadge syncing={syncing} />
      <div className="card text-center">
        <p className="label">Room code</p>
        <button type="button" onClick={copyCode} className="group inline-flex items-center gap-3" title="Copy room code">
          <span ref={codeRef} className="font-mono text-5xl font-bold tracking-[0.3em] text-indigo-200">
            {session.room_id}
          </span>
          {copyState === 'copied' ? <Check className="h-5 w-5 text-good" /> : <Copy className="h-5 w-5 text-muted group-hover:text-ink" />}
        </button>
        <p className="mt-2 text-sm text-muted" aria-live="polite">
          {copyState === 'copied'
            ? 'Copied. Share it with your friends.'
            : copyState === 'manual'
              ? 'Copying is blocked here. The code is selected: press Cmd+C or Ctrl+C.'
              : 'Tap the code to copy it, then share it with friends.'}
        </p>
      </div>

      <div className="card mt-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-semibold">
            <Users className="h-4 w-4" /> Players
          </h2>
          <span className="text-sm text-slate-400">
            {players.length} / {MAX_PLAYERS}
          </span>
        </div>
        <ul className="space-y-2">
          {players.map((p) => (
            <li key={p.player_id} className="flex items-center gap-3 rounded-lg bg-slate-950 px-3 py-2">
              <span className="font-medium">{p.name}</span>
              {p.player_id === session.player_id && <span className="text-xs text-slate-500">(you)</span>}
              {p.is_host && <Crown className="h-4 w-4 text-amber-300" aria-label="Host" />}
              <span className="ml-auto rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">
                Ready
              </span>
            </li>
          ))}
          {!lobby && <li className="text-sm text-slate-500">Loading players…</li>}
        </ul>
      </div>

      <div className="mt-4 flex flex-col gap-2">
        {isHost ? (
          <>
            <button type="button" className="btn-primary" disabled={!canStart || starting} onClick={start}>
              <Play className="h-4 w-4" /> {starting ? 'Starting…' : 'Start Game'}
            </button>
            {players.length < MIN_PLAYERS && (
              <p className="text-center text-xs text-slate-500">
                Need at least {MIN_PLAYERS} players ({MIN_PLAYERS - players.length} more).
              </p>
            )}
          </>
        ) : (
          <p className="text-center text-sm text-slate-400">Waiting for the host to start the game…</p>
        )}
        {error && <p className="text-center text-sm text-rose-400">{error}</p>}
        <button type="button" className="btn-ghost" onClick={leave} disabled={leaving}>
          <LogOut className="h-4 w-4" /> {leaving ? 'Leaving…' : 'Leave'}
        </button>
      </div>
    </div>
  );
}
