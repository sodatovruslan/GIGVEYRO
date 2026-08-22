"use client";

import { useEffect, useState } from "react";

import { useLocalizedError } from "@/features/i18n/use-localized-error";

export function useApiQuery<T>(loader: () => Promise<T>, queryKey = "default", enabled = true) {
  const localizeError = useLocalizedError();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");

  async function load() {
    if (!enabled) return;
    setLoading(true);
    setError("");
    try {
      setData(await loader());
    } catch (reason) {
      setError(localizeError(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void Promise.resolve()
      .then(loader)
      .then((result) => {
        if (active) { setData(result); setError(""); setLoading(false); }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(localizeError(reason));
          setLoading(false);
        }
      });
    return () => { active = false; };
  // The caller supplies a semantic key for each loader input.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, enabled]);
  return { data, loading, error, refetch: load, setData };
}
