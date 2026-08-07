import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
const KEY = "n2e-theme";
const listeners = new Set<() => void>();

function current(): Theme {
  return (document.documentElement.dataset.theme as Theme) ?? "dark";
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, current, () => "dark" as Theme);
  const toggle = useCallback(() => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem(KEY, next);
    listeners.forEach((fn) => fn());
  }, []);
  return [theme, toggle];
}
