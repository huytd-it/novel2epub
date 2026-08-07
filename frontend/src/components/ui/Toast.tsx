import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import clsx from "clsx";

type ToastTone = "ok" | "error" | "info";
interface Toast {
  id: number;
  tone: ToastTone;
  text: string;
}

const ToastContext = createContext<(text: string, tone?: ToastTone) => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

const styles: Record<ToastTone, string> = {
  ok: "alert-success",
  error: "alert-error",
  info: "alert-info",
};

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const push = useCallback((text: string, tone: ToastTone = "ok") => {
    const id = nextId++;
    setItems((prev) => [...prev, { id, tone, text }]);
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 5000);
  }, []);

  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast toast-end z-100" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={clsx("alert alert-soft text-[13px]", styles[t.tone])}>
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
