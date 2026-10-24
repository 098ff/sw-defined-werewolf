// Inline SVG role illustrations: no image assets to ship, sharp at any size, readable on day and night themes.
const ART = {
  WEREWOLF: {
    bg: '#4A1B0C',
    draw: (
      <>
        <path d="M14 12 L25 24 L39 24 L50 12 L48 35 Q45 47 32 54 Q19 47 16 35 Z" fill="#F0997B" />
        <path d="M18 18 L23 25 L19 27 Z M46 18 L41 25 L45 27 Z" fill="#993C1D" />
        <path d="M22 33 L29 35 L22 37 Z M42 33 L35 35 L42 37 Z" fill="#FAC775" />
        <path d="M27 43 Q32 47 37 43 L32 50 Z" fill="#4A1B0C" />
      </>
    )
  },
  SEER: {
    bg: '#042C53',
    draw: (
      <>
        <circle cx="32" cy="28" r="14" fill="#85B7EB" />
        <ellipse cx="27" cy="23" rx="4" ry="2.5" fill="#E6F1FB" opacity="0.8" />
        <path d="M21 44 H43 L47 52 H17 Z" fill="#378ADD" />
        <path d="M48 12 l1.5 4 4 1.5 -4 1.5 -1.5 4 -1.5 -4 -4 -1.5 4 -1.5 Z" fill="#E6F1FB" />
        <path d="M15 18 l1 2.5 2.5 1 -2.5 1 -1 2.5 -1 -2.5 -2.5 -1 2.5 -1 Z" fill="#B5D4F4" />
      </>
    )
  },
  DOCTOR: {
    bg: '#04342C',
    draw: (
      <>
        <path d="M25 22 V18 a4 4 0 0 1 4 -4 h6 a4 4 0 0 1 4 4 V22" fill="none" stroke="#9FE1CB" strokeWidth="3" />
        <rect x="13" y="22" width="38" height="28" rx="5" fill="#5DCAA5" />
        <rect x="29" y="28" width="6" height="16" rx="1" fill="#E1F5EE" />
        <rect x="24" y="33" width="16" height="6" rx="1" fill="#E1F5EE" />
      </>
    )
  },
  VILLAGER: {
    bg: '#412402',
    draw: (
      <>
        <rect x="40" y="15" width="5" height="11" fill="#854F0B" />
        <rect x="17" y="30" width="30" height="22" fill="#FAEEDA" />
        <path d="M11 31 L32 14 L53 31 Z" fill="#EF9F27" />
        <rect x="28" y="38" width="8" height="14" rx="1" fill="#854F0B" />
        <rect x="20" y="34" width="6" height="6" fill="#FAC775" />
        <rect x="38" y="34" width="6" height="6" fill="#FAC775" />
      </>
    )
  }
};

const HIDDEN = {
  bg: '#2C2C2A',
  draw: <path d="M26 26 a6 6 0 1 1 9 5 c-2 1.2 -3 2.4 -3 5 M32 43 v0.5" fill="none" stroke="#B4B2A9" strokeWidth="3.5" strokeLinecap="round" />
};

export default function RoleArt({ role, size = 64, className = '' }) {
  const art = ART[role] ?? HIDDEN;
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} role="img" aria-label={role ? `${role.toLowerCase()} illustration` : 'hidden role'}>
      <circle cx="32" cy="32" r="32" fill={art.bg} />
      {art.draw}
    </svg>
  );
}
