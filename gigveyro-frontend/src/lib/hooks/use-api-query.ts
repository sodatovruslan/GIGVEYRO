"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useLocalizedError } from "@/features/i18n/use-localized-error";
import { queryInvalidation } from "@/lib/query/invalidation";

export function useApiQuery<T>(loader: () => Promise<T>, queryKey = "default", enabled = true) {
  const localizeError = useLocalizedError();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const loaderRef = useRef(loader);
  const localizeErrorRef = useRef(localizeError);
  const activeRef = useRef(false);
  const requestRef = useRef(0);

  useEffect(() => {
    loaderRef.current = loader;
    localizeErrorRef.current = localizeError;
  }, [loader, localizeError]);

  const load = useCallback(async () => {
    if (!enabled) return;
    const request = ++requestRef.current;
    setLoading(true);
    setError("");
    try {
      const result = await loaderRef.current();
      if (activeRef.current && request === requestRef.current) setData(result);
    } catch (reason) {
      if (activeRef.current && request === requestRef.current) {
        setError(localizeErrorRef.current(reason));
      }
    } finally {
      if (activeRef.current && request === requestRef.current) setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    activeRef.current = true;
    if (!enabled) {
      return () => { activeRef.current = false; };
    }
    void Promise.resolve().then(load);
    const unsubscribe = queryInvalidation.subscribe(queryKey, () => void load());
    return () => {
      activeRef.current = false;
      requestRef.current += 1;
      unsubscribe();
    };
  }, [enabled, load, queryKey]);
  return { data, loading, error, refetch: load, setData };
}
