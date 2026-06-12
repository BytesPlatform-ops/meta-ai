import { useEffect, useRef } from "react";

const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

export function useAutoRefresh(callback: () => void, enabled: boolean = true) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => savedCallback.current(), REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, [enabled]);
}
