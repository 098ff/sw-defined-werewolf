import { useEffect, useMemo, useRef, useState } from 'react';
import { MessageSquare, Send, X } from 'lucide-react';
import { chatApi } from '../api/client';
import { usePolling } from '../hooks/usePolling';

const MAX_LEN = 280;

// Which channels a player may read, and whether they may post right now (mirrors chat service rules).
function channelRules(me, phase) {
  const wolf = me.role === 'WEREWOLF';
  const rules = [
    {
      id: 'PUBLIC',
      label: 'Public',
      canPost: me.alive && phase === 'DAY',
      reason: !me.alive ? 'The dead cannot speak in public.' : 'Public chat opens during the day.'
    }
  ];
  if (wolf) {
    rules.push({
      id: 'WOLF',
      label: 'Wolf',
      canPost: me.alive && phase === 'NIGHT',
      reason: !me.alive ? 'Dead wolves cannot howl.' : 'The pack speaks only at night.'
    });
  }
  if (!me.alive || phase === 'ENDED') {
    rules.push({ id: 'DEAD', label: 'Dead', canPost: !me.alive, reason: 'Only the dead may post here.' });
  }
  return rules;
}

function defaultChannel(me, phase) {
  if (!me.alive) return 'DEAD';
  if (phase === 'NIGHT' && me.role === 'WEREWOLF') return 'WOLF';
  return 'PUBLIC';
}

// `visible` is false while the phone drawer is closed; unread counts are reported via onUnreadChange.
export default function ChatPanel({ session, state, visible = true, onUnreadChange, onClose }) {
  const { me, phase } = state;
  const [messages, setMessages] = useState([]);
  const lastIdRef = useRef(0);
  const [channel, setChannel] = useState(() => defaultChannel(me, phase));
  const [text, setText] = useState('');
  const [error, setError] = useState(null);
  const listRef = useRef(null);
  const seenRef = useRef({});
  const seenTotalRef = useRef(0);

  usePolling(
    async () => {
      const res = await chatApi.list(session.room_id, session.player_token, lastIdRef.current);
      const incoming = res.ok ? res.data?.messages ?? [] : [];
      if (incoming.length) {
        lastIdRef.current = Math.max(lastIdRef.current, ...incoming.map((m) => m.message_id));
        setMessages((prev) => {
          const known = new Set(prev.map((m) => m.message_id));
          return [...prev, ...incoming.filter((m) => !known.has(m.message_id))];
        });
      }
      return res;
    },
    { deps: [session.room_id, session.player_token] }
  );

  // Follow the phase: jump to the channel that's relevant now.
  useEffect(() => {
    setChannel(defaultChannel(me, phase));
  }, [phase, me.alive, me.role]);

  const rules = channelRules(me, phase);
  const active = rules.find((r) => r.id === channel) ?? rules[0];
  const channelMessages = useMemo(() => messages.filter((m) => m.channel === active.id), [messages, active.id]);

  const unread = (id) => messages.filter((m) => m.channel === id).length - (seenRef.current[id] ?? 0);
  useEffect(() => {
    seenRef.current[active.id] = channelMessages.length;
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [channelMessages.length, active.id]);

  useEffect(() => {
    if (visible) seenTotalRef.current = messages.length;
    onUnreadChange?.(visible ? 0 : messages.length - seenTotalRef.current);
  }, [visible, messages.length, onUnreadChange]);

  const send = async (e) => {
    e.preventDefault();
    const body = text.trim();
    if (!body) return;
    setError(null);
    const res = await chatApi.send(session.room_id, session.player_token, active.id, body);
    if (res.ok) setText('');
    else setError(res.error?.message || res.error?.code);
  };

  return (
    <div className="card flex h-full min-h-[20rem] flex-col">
      <div className="mb-2 flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-muted" />
        <div role="tablist" className="flex gap-1">
          {rules.map((r) => {
            const n = r.id === active.id ? 0 : unread(r.id);
            return (
              <button
                key={r.id}
                role="tab"
                type="button"
                aria-selected={r.id === active.id}
                onClick={() => setChannel(r.id)}
                className={`rounded-md px-3 py-1 text-xs font-semibold ${
                  r.id === active.id ? 'bg-accent text-on-accent' : 'text-muted hover:bg-sunken'
                }`}
              >
                {r.label}
                {n > 0 && <span className="ml-1 rounded-full bg-accent px-1.5 text-[10px] text-on-accent">{n}</span>}
              </button>
            );
          })}
        </div>
        {onClose && (
          <button type="button" onClick={onClose} className="ml-auto rounded p-1 text-muted hover:text-ink md:hidden" aria-label="Close chat">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <div ref={listRef} className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-lg bg-sunken/70 p-3 text-sm">
        {channelMessages.length === 0 && <p className="text-muted">No messages yet.</p>}
        {channelMessages.map((m) => (
          <div key={m.message_id}>
            <span className={`font-semibold ${m.sender_id === me.player_id ? 'text-accent' : 'text-ink'}`}>{m.sender_name}</span>
            <span className="ml-2 text-[10px] text-muted">{new Date(m.created_at * 1000).toLocaleTimeString()}</span>
            <p className="break-words">{m.text}</p>
          </div>
        ))}
      </div>

      <form onSubmit={send} className="mt-2 flex gap-2">
        <input
          className="input"
          value={text}
          maxLength={MAX_LEN}
          disabled={!active.canPost}
          placeholder={active.canPost ? `Message #${active.label.toLowerCase()}` : active.reason}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className="btn-primary px-3" disabled={!active.canPost || !text.trim()} aria-label="Send">
          <Send className="h-4 w-4" />
        </button>
      </form>
      {error && <p className="mt-1 text-xs text-bad">{error}</p>}
    </div>
  );
}
