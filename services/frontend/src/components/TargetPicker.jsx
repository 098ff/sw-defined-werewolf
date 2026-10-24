// Radio-card target selector used inside the "Your move" card.
export default function TargetPicker({ name, candidates, value, onChange, disabled }) {
  return (
    <div role="radiogroup" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {candidates.map((p) => {
        const selected = value === p.player_id;
        return (
          <label
            key={p.player_id}
            className={`cursor-pointer rounded-lg border px-3 py-2 text-center text-sm font-medium transition ${
              selected ? 'border-accent bg-accent text-on-accent' : 'border-move-muted/30 bg-move hover:border-move-muted'
            } ${p.dashed && !selected ? 'border-dashed' : ''} ${disabled ? 'pointer-events-none opacity-70' : ''}`}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              value={p.player_id}
              checked={selected}
              disabled={disabled}
              onChange={() => onChange(p.player_id)}
            />
            {p.label ?? p.name}
          </label>
        );
      })}
    </div>
  );
}
