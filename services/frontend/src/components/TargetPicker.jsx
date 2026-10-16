// Radio-card target selector shared by night actions and day voting.
export default function TargetPicker({ name, candidates, value, onChange, disabled, extra }) {
  return (
    <div role="radiogroup" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {candidates.map((p) => (
        <label
          key={p.player_id}
          className={`cursor-pointer rounded-lg border px-3 py-2 text-sm transition ${
            value === p.player_id ? 'border-indigo-400 bg-indigo-500/20 text-white' : 'border-slate-700 bg-slate-950 hover:border-slate-500'
          } ${disabled ? 'pointer-events-none opacity-60' : ''}`}
        >
          <input
            type="radio"
            name={name}
            className="sr-only"
            value={p.player_id}
            checked={value === p.player_id}
            disabled={disabled}
            onChange={() => onChange(p.player_id)}
          />
          {p.label ?? p.name}
        </label>
      ))}
      {extra}
    </div>
  );
}
