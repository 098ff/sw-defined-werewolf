import { RotateCcw, Trophy } from 'lucide-react';
import { ROLE_INFO, roleLabel } from '../api/roles';
import RoleArt from './RoleArt';

export default function GameOverModal({ state, onExit }) {
  const wolvesWon = state.winner === 'WEREWOLF';
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
        <div className="text-center">
          <Trophy className={`mx-auto h-10 w-10 ${wolvesWon ? 'text-rose-400' : 'text-emerald-400'}`} />
          <h2 className="mt-2 text-3xl font-bold">{wolvesWon ? 'Werewolves Win!' : 'Villagers Win!'}</h2>
          {state.announcement && <p className="mt-1 text-sm text-slate-400">{state.announcement}</p>}
        </div>
        <table className="mt-5 w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Player</th>
              <th className="pb-2">Role</th>
              <th className="pb-2 text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {state.players.map((p) => (
              <tr key={p.player_id} className="border-t border-slate-800">
                <td className="py-2">
                  {p.name}
                  {p.player_id === state.me.player_id && <span className="text-slate-500"> (you)</span>}
                </td>
                <td className={`py-2 ${ROLE_INFO[p.role]?.tone.split(' ')[0] ?? ''}`}>
                  <span className="flex items-center gap-2">
                    <RoleArt role={p.role} size={22} /> {roleLabel(p.role)}
                  </span>
                </td>
                <td className={`py-2 text-right ${p.alive ? 'text-emerald-300' : 'text-slate-500'}`}>{p.alive ? 'Alive' : 'Dead'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="btn-primary mt-6 w-full" onClick={onExit}>
          <RotateCcw className="h-4 w-4" /> Back to Lobby / New Game
        </button>
      </div>
    </div>
  );
}
