// Decorative phase backdrop: stars and moon glow at night, sun glow by day. Cross-fades on phase change.
const STARS = Array.from({ length: 70 }, (_, i) => {
  // Deterministic pseudo-random layout so stars don't jump between renders.
  const r = (n) => ((Math.sin(i * 12.9898 + n * 78.233) * 43758.5453) % 1 + 1) % 1;
  return { left: r(1) * 100, top: r(2) * 70, size: r(3) > 0.85 ? 3 : 2, opacity: 0.25 + r(4) * 0.6 };
});

export default function SkyBackdrop({ phase }) {
  const night = phase === 'NIGHT';
  const day = phase === 'DAY';
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div className={`absolute inset-0 transition-opacity duration-1000 ${night ? 'opacity-100' : 'opacity-0'}`}>
        {STARS.map((s, i) => (
          <span
            key={i}
            className="absolute rounded-full bg-white"
            style={{ left: `${s.left}%`, top: `${s.top}%`, width: s.size, height: s.size, opacity: s.opacity }}
          />
        ))}
        <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-indigo-200/10 blur-3xl" />
      </div>
      <div className={`absolute inset-0 transition-opacity duration-1000 ${day ? 'opacity-100' : 'opacity-0'}`}>
        <div className="absolute -right-20 -top-20 h-96 w-96 rounded-full bg-amber-300/50 blur-3xl" />
        <div className="absolute -left-32 bottom-0 h-72 w-[40rem] rounded-full bg-orange-200/40 blur-3xl" />
      </div>
    </div>
  );
}
