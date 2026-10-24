import { useState } from 'react';
import { DoorOpen, Moon, Plus } from 'lucide-react';
import { lobbyApi } from '../api/client';

const NAME_MIN = 2;
const NAME_MAX = 20;

function validateName(raw) {
  const name = raw.trim();
  if (name.length < NAME_MIN || name.length > NAME_MAX) return [null, `Name must be ${NAME_MIN}–${NAME_MAX} characters.`];
  return [name, null];
}

export default function Landing({ onEnter }) {
  const [tab, setTab] = useState('create');
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const [cleanName, nameErr] = validateName(name);
    if (nameErr) return setError(nameErr);
    const roomCode = code.trim().toUpperCase();
    if (tab === 'join' && !/^[A-Z0-9]{4}$/.test(roomCode)) return setError('Room code is 4 characters.');

    setBusy(true);
    setError(null);
    const res = tab === 'create' ? await lobbyApi.create(cleanName) : await lobbyApi.join(roomCode, cleanName);
    setBusy(false);
    if (!res.ok) return setError(res.error?.message || res.error?.code || 'Something went wrong.');
    onEnter({ ...res.data, name: cleanName });
  };

  return (
    <div className="mx-auto flex min-h-[80vh] max-w-md flex-col justify-center px-4">
      <div className="mb-8 text-center">
        <Moon className="mx-auto mb-3 h-10 w-10 text-indigo-300" />
        <h1 className="text-3xl font-bold tracking-tight">Werewolf</h1>
        <p className="mt-1 text-sm text-slate-400">4–6 players · one village · someone is lying</p>
      </div>

      <div className="card">
        <div role="tablist" className="mb-4 grid grid-cols-2 gap-1 rounded-lg bg-slate-950 p-1">
          {[
            ['create', 'Create Room', Plus],
            ['join', 'Join Room', DoorOpen]
          ].map(([key, label, Icon]) => (
            <button
              key={key}
              role="tab"
              type="button"
              aria-selected={tab === key}
              onClick={() => {
                setTab(key);
                setError(null);
              }}
              className={`flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium ${
                tab === key ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Icon className="h-4 w-4" /> {label}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-4">
          {tab === 'join' && (
            <div>
              <label className="label" htmlFor="code">
                Room code
              </label>
              <input
                id="code"
                className="input font-mono uppercase tracking-[0.4em]"
                maxLength={4}
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="WOLF"
                autoComplete="off"
              />
            </div>
          )}
          <div>
            <label className="label" htmlFor="name">
              Your name
            </label>
            <input
              id="name"
              className="input"
              maxLength={NAME_MAX}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Alice"
              autoComplete="off"
            />
          </div>
          {error && <p className="text-sm text-rose-400">{error}</p>}
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Contacting gateway…' : tab === 'create' ? 'Create room' : 'Join room'}
          </button>
        </form>
      </div>
    </div>
  );
}
