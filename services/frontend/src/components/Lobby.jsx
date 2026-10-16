import { useState } from 'react';
import { Check, Copy, Crown, LogOut, Play, Users } from 'lucide-react';
import { isSessionGone, lobbyApi } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import SyncBadge from './SyncBadge';

const MIN_PLAYERS = 4;
const MAX_PLAYERS = 6;

export default function Lobby({ session, onStarted, onLeave }) {
  const [lobby, setLobby] = useState(null);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [copied, setCopied] = useState(false);

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
    try {
      await navigator.clipboard.writeText(session.room_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  return (
    <div className="mx-auto max-w-xl px-4 pt-10">
      <SyncBadge syncing={syncing} />
      <div className="card text-center">
        <p className="label">Room code</p>
        <button type="button" onClick={copyCode} className="group inline-flex items-center gap-3" title="Copy room code">
          <span className="font-mono text-5xl font-bold tracking-[0.3em] text-indigo-200">{session.room_id}</span>
          {copied ? <Check className="h-5 w-5 text-emerald-400" /> : <Copy className="h-5 w-5 text-slate-500 group-hover:text-slate-300" />}
        </button>
        <p className="mt-2 text-sm text-slate-400">Share this code with friends to join.</p>
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
        <button type="button" className="btn-ghost" onClick={() => onLeave()}>
          <LogOut className="h-4 w-4" /> Leave
        </button>
      </div>
    </div>
  );
}
