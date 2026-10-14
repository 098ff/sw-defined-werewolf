import React, { useState, useEffect } from 'react';

export default function App() {
  const [gatewayStatus, setGatewayStatus] = useState('Checking...');
  const [traceData, setTraceData] = useState([]);
  const [roomCode, setRoomCode] = useState('');
  const [playerName, setPlayerName] = useState('');

  useEffect(() => {
    // Health check via Gateway
    fetch('/health/ready')
      .then((res) => res.json())
      .then((data) => {
        setGatewayStatus(data.ok ? 'Online' : 'Error');
        if (data.trace) setTraceData(data.trace);
      })
      .catch(() => setGatewayStatus('Offline / Unreachable'));
  }, []);

  const handleCreateRoom = async () => {
    if (!playerName.trim()) return alert('Please enter your name');
    try {
      const res = await fetch('/api/lobby/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: playerName })
      });
      const json = await res.json();
      if (json.ok) {
        setRoomCode(json.data.room_id);
        if (json.trace) setTraceData(json.trace);
        sessionStorage.setItem('player_token', json.data.player_token);
        sessionStorage.setItem('room_id', json.data.room_id);
        alert(`Room created! Code: ${json.data.room_id}`);
      } else {
        alert(json.error?.message || 'Error creating room');
      }
    } catch (err) {
      alert(`Network error: ${err.message}`);
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: '40px auto', padding: 24, background: '#1e293b', borderRadius: 12 }}>
      <header style={{ borderBottom: '1px solid #334155', paddingBottom: 16, marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 'bold' }}>🐺 Werewolf SDS — Multi-Node Kubernetes</h1>
        <p style={{ color: '#94a3b8', fontSize: 14 }}>
          Gateway Status: <span style={{ color: gatewayStatus === 'Online' ? '#4ade80' : '#f87171' }}>{gatewayStatus}</span>
        </p>
      </header>

      <main>
        <div style={{ background: '#0f172a', padding: 20, borderRadius: 8, marginBottom: 24 }}>
          <h2 style={{ fontSize: 18, marginBottom: 12 }}>Join or Create Room</h2>
          <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
            <input
              type="text"
              placeholder="Your Name"
              value={playerName}
              onChange={(e) => setPlayerName(e.target.value)}
              style={{ flex: 1, padding: 10, borderRadius: 6, border: '1px solid #334155', background: '#1e293b', color: '#fff' }}
            />
            <button
              onClick={handleCreateRoom}
              style={{ padding: '10px 20px', borderRadius: 6, border: 'none', background: '#3b82f6', color: '#fff', cursor: 'pointer', fontWeight: 'bold' }}
            >
              Create Room
            </button>
          </div>
          {roomCode && (
            <p style={{ color: '#38bdf8' }}>Active Room Code: <strong>{roomCode}</strong></p>
          )}
        </div>
      </main>

      {/* Cross-Node System Trace HUD */}
      <footer style={{ marginTop: 32, padding: 16, background: '#0f172a', borderRadius: 8, border: '1px solid #334155' }}>
        <h3 style={{ fontSize: 14, color: '#94a3b8', marginBottom: 8 }}>🛰️ Real-Time Request Trace (SDN Cross-Node Proof):</h3>
        {traceData.length > 0 ? (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {traceData.map((hop, idx) => (
              <span key={idx} style={{ padding: '4px 8px', borderRadius: 4, background: '#334155', fontSize: 12 }}>
                <strong>{hop.service}</strong> ({hop.pod} @ <span style={{ color: '#38bdf8' }}>{hop.node}</span>)
                {idx < traceData.length - 1 && ' ➔ '}
              </span>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 12, color: '#64748b' }}>No trace recorded yet. Perform an action to see hops.</p>
        )}
      </footer>
    </div>
  );
}
