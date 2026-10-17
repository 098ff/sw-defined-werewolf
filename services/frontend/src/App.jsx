import { useState } from 'react';
import { clearSession, loadSession, saveSession } from './api/session';
import Game from './components/Game';
import Landing from './components/Landing';
import Lobby from './components/Lobby';
import TraceHUD from './components/TraceHUD';

export default function App() {
  const [session, setSession] = useState(loadSession);
  // A restored session starts in the lobby; the lobby poll forwards to the game if it already started.
  const [stage, setStage] = useState(session ? 'lobby' : 'landing');
  const [notice, setNotice] = useState(null);

  const enter = (data) => {
    const s = {
      room_id: data.room_id,
      player_id: data.player_id,
      player_token: data.player_token,
      is_host: data.is_host,
      name: data.name
    };
    saveSession(s);
    setSession(s);
    setNotice(null);
    setStage('lobby');
  };

  const exit = (message) => {
    clearSession();
    setSession(null);
    setNotice(message ?? null);
    setStage('landing');
  };

  return (
    <>
      {notice && stage === 'landing' && (
        <div className="mx-auto mt-4 max-w-md rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm text-amber-200">
          {notice}
        </div>
      )}
      {stage === 'landing' && <Landing onEnter={enter} />}
      {stage === 'lobby' && session && <Lobby session={session} onStarted={() => setStage('game')} onLeave={exit} />}
      {stage === 'game' && session && <Game session={session} onExit={exit} />}
      <TraceHUD />
    </>
  );
}
