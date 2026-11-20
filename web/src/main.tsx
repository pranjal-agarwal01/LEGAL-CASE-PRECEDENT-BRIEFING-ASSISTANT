import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Shell } from "@/components/Shell";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { SessionProvider, useSession, useTheme } from "@/lib/session";
import { AuthPage } from "@/pages/Auth";
import { AuthorityPage, LibraryPage } from "@/pages/Library";
import { MatterFormPage } from "@/pages/MatterForm";
import { MatterPage } from "@/pages/MatterPage";
import { MattersPage } from "@/pages/Matters";
import { TeamPage } from "@/pages/Team";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, e) => !(e instanceof ApiError && [401, 403, 404].includes(e.status)) && n < 2,
      refetchOnWindowFocus: false,
    },
  },
});

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  const location = useLocation();
  if (loading) return <p className="p-8 text-muted-foreground">Loading…</p>;
  if (!me) return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  if (me.must_change_password && location.pathname !== "/team") return <Navigate to="/team" replace />;
  return <Shell>{children}</Shell>;
}

function ThemedToaster() {
  const [theme] = useTheme();
  return <Toaster theme={theme} position="bottom-right" />;
}

function App() {
  return (
    <Routes>
      <Route path="/signin" element={<AuthPage />} />
      <Route path="/matters" element={<RequireAuth><MattersPage /></RequireAuth>} />
      <Route path="/matters/new" element={<RequireAuth><MatterFormPage /></RequireAuth>} />
      <Route path="/matters/:id" element={<RequireAuth><MatterPage /></RequireAuth>} />
      <Route path="/matters/:id/edit" element={<RequireAuth><MatterFormPage /></RequireAuth>} />
      <Route path="/library" element={<RequireAuth><LibraryPage /></RequireAuth>} />
      <Route path="/library/:id" element={<RequireAuth><AuthorityPage /></RequireAuth>} />
      <Route path="/team" element={<RequireAuth><TeamPage /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/matters" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SessionProvider>
          <TooltipProvider>
            <App />
            <ThemedToaster />
          </TooltipProvider>
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
