// Night action names; must match ACTION_BY_ROLE in services/gamemaster/app/engine.py.
export const NIGHT_ACTIONS = {
  WEREWOLF: 'WEREWOLF_KILL',
  DOCTOR: 'DOCTOR_PROTECT',
  SEER: 'SEER_CHECK'
};

export const ROLE_INFO = {
  WEREWOLF: {
    label: 'Werewolf',
    alignment: 'Werewolves',
    description: 'Each night, pick a villager to attack. Blend in by day and survive the vote.',
    tone: 'text-rose-300 border-rose-500/40 bg-rose-500/10'
  },
  SEER: {
    label: 'Seer',
    alignment: 'Village',
    description: "Each night, inspect one player to learn whether they're a Werewolf.",
    tone: 'text-sky-300 border-sky-500/40 bg-sky-500/10'
  },
  DOCTOR: {
    label: 'Doctor',
    alignment: 'Village',
    description: 'Each night, protect one player (yourself included) from the werewolf attack.',
    tone: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'
  },
  VILLAGER: {
    label: 'Villager',
    alignment: 'Village',
    description: 'No night power. Read the room by day and vote out the werewolves.',
    tone: 'text-amber-200 border-amber-500/40 bg-amber-500/10'
  }
};

export const roleLabel = (role) => ROLE_INFO[role]?.label ?? 'Unknown';
