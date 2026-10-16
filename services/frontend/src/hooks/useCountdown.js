import { useEffect, useState } from 'react';
import { serverNow } from '../api/client';

// Seconds left until a server epoch-seconds deadline. Display only: the server decides transitions.
export function useCountdown(endTimeSec) {
  const calc = () => (endTimeSec ? Math.max(0, Math.ceil(endTimeSec - serverNow() / 1000)) : 0);
  const [left, setLeft] = useState(calc);

  useEffect(() => {
    setLeft(calc());
    const id = setInterval(() => setLeft(calc()), 250);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endTimeSec]);

  return left;
}
