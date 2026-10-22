"use client";

import { useEffect, useState } from "react";
import useSWR, { type SWRConfiguration } from "swr";

import { api } from "./api";

const STATIC: SWRConfiguration = { revalidateOnFocus: false, dedupingInterval: 5 * 60_000 };

export function useDebounced<T>(value: T, delayMs = 200): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

export const useCategories = () => useSWR("categories", api.categories, STATIC);
export const useTeams = () => useSWR("teams", api.teams, STATIC);

export const useSyncStatus = () =>
  useSWR("sync-status", api.syncStatus, { refreshInterval: 30_000 });
