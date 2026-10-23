import { RefreshCw } from 'lucide-react';

// Shown while a poll is failing and backing off (e.g. a pod is being rescheduled).
export default function SyncBadge({ syncing }) {
  if (!syncing) return null;
  return (
    <div className="fixed right-3 top-3 z-50 flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs text-amber-200">
      <RefreshCw className="h-3 w-3 animate-spin" /> Syncing…
    </div>
  );
}
