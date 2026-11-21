import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError, type Me, type Meta } from "@/lib/api";

type SessionValue = { me: Me | null; meta: Meta | undefined; loading: boolean; refresh: () => void; signOut: () => Promise<void> };
const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
  const metaQuery = useQuery({ queryKey: ["meta"], queryFn: () => api<Meta>("/meta"), staleTime: 5 * 60_000 });
  const refresh = useCallback(() => void qc.invalidateQueries({ queryKey: ["me"] }), [qc]);
  const signOut = useCallback(async () => {
    await api("/auth/logout", { method: "POST" });
    qc.clear();
    qc.setQueryData(["me"], null);
  }, [qc]);
  return (
    <SessionContext.Provider
      value={{ me: meQuery.data ?? null, meta: metaQuery.data, loading: meQuery.isLoading, refresh, signOut }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}

type Theme = "light" | "dark" | "system";

function apply(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("theme") as Theme) || "light";
    } catch {
      return "light";
    }
  });
  useEffect(() => {
    apply(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);
  const set = useCallback((t: Theme) => {
    try {
      localStorage.setItem("theme", t);
    } catch {
      /* storage unavailable */
    }
    setTheme(t);
  }, []);
  return [theme, set];
}
