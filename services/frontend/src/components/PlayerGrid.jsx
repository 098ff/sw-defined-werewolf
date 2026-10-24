import { Skull, User } from 'lucide-react';
import { roleLabel } from '../api/roles';

export default function PlayerGrid({ players, meId }) {
  return (
    <div className="card">
      <h3 className="mb-3 text-sm font-semibold text-muted">Villagers</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {players.map((p) => (
          <div
            key={p.player_id}
            className={`flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm ${
              p.alive ? 'bg-sunken/70' : 'bg-sunken/30 text-muted'
            }`}
          >
            {p.alive ? <User className="h-4 w-4 shrink-0" /> : <Skull className="h-4 w-4 shrink-0" />}
            <span className={`truncate ${p.alive ? '' : 'line-through'}`}>{p.name}</span>
            {p.player_id === meId && <span className="text-xs text-muted">(you)</span>}
            {p.role && p.player_id !== meId && <span className="ml-auto text-[10px] font-semibold uppercase text-bad">{roleLabel(p.role)}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
