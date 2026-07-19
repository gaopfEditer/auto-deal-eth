import { useCallback, useEffect, useRef, useState } from "react";
import type { PatternPayload, RadarSnapshot } from "../types";
import { EMPTY_SNAPSHOT } from "../types";

export function useRadarSSE(intervalMs = 5000) {
  const [snapshot, setSnapshot] = useState<RadarSnapshot>(EMPTY_SNAPSHOT);
  const [online, setOnline] = useState(false);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const apply = useCallback((data: RadarSnapshot) => {
    setSnapshot(data);
  }, []);

  /** 本地补丁：watch/pin/remove 等 API 成功后立刻反映，不必等下一轮 SSE */
  const patchPattern = useCallback((partial: Partial<PatternPayload>) => {
    setSnapshot((prev) => ({
      ...prev,
      pattern: {
        ...(prev.pattern ?? EMPTY_SNAPSHOT.pattern!),
        ...partial,
      },
    }));
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;

    const bootstrap = async () => {
      try {
        const res = await fetch("/api/snapshot");
        if (!res.ok) throw new Error(String(res.status));
        apply(await res.json());
        setOnline(true);
      } catch {
        setOnline(false);
      }
    };

    const connect = () => {
      if (cancelled) return;
      es = new EventSource("/api/stream");
      es.onopen = () => setOnline(true);
      es.onmessage = (ev) => {
        try {
          apply(JSON.parse(ev.data));
        } catch {
          /* ignore malformed */
        }
      };
      es.onerror = () => {
        setOnline(false);
        es?.close();
        retryRef.current = setTimeout(connect, intervalMs);
      };
    };

    bootstrap().then(connect);

    return () => {
      cancelled = true;
      es?.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [apply, intervalMs]);

  return { snapshot, online, patchPattern };
}
