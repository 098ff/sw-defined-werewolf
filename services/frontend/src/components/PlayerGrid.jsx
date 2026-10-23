import { Skull, User } from 'lucide-react';
import { roleLabel } from '../api/roles';

export default function PlayerGrid({ players, meId }) {
  return (
    <div className="card">
      <h3 className="mb-3 text-sm font-semibold text-slate-300">Villagers</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {players.map((p) => (
          <div
            key={p.player_id}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
              p.alive ? 'border-slate-700 bg-slate-950' : 'border-slate-800 bg-slate-900 text-slate-500 line-through'
            }`}
          >
            {p.alive ? <User className="h-4 w-4 shrink-0" /> : <Skull className="h-4 w-4 shrink-0" />}
            <span className="truncate">{p.name}</span>
            {p.player_id === meId && <span className="text-xs text-slate-500 no-underline">(you)</span>}
            {p.role && p.player_id !== meId && (
              <span className="ml-auto text-[10px] uppercase text-rose-300">{roleLabel(p.role)}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
