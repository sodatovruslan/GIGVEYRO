"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/error";

export function useApiQuery<T>(loader: () => Promise<T>, queryKey = "default") {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await loader());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Не удалось загрузить данные.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    void Promise.resolve()
      .then(loader)
      .then((result) => {
        if (active) { setData(result); setError(""); setLoading(false); }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof ApiError ? reason.message : "Не удалось загрузить данные.");
          setLoading(false);
        }
      });
    return () => { active = false; };
  // The caller supplies a semantic key for each loader input.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);
  return { data, loading, error, refetch: load, setData };
}
