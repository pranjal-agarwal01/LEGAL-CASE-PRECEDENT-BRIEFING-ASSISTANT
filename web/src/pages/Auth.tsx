import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Logo } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Me } from "@/lib/api";
import { useSession } from "@/lib/session";

function Field({ id, label, hint, ...props }: { id: string; label: string; hint?: string } & React.ComponentProps<typeof Input>) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} name={id} className="h-10 bg-card" {...props} />
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Specimen() {
  return (
    <figure className="mt-10 max-w-[34rem] rounded-md border bg-card p-5 sm:p-6">
      <div className="brief grid grid-cols-[1.75rem_1fr] gap-x-3 text-[15.5px]">
        <span className="mark mark-supported mt-1" aria-label="Verified against source">✓</span>
        <p>
          Specific performance cannot be granted to a plaintiff who fails to prove that they have always been
          ready and willing to perform their part of the agreement.{" "}
          <span className="cite">Specific Relief Act, 1963, s 16(c)</span>
        </p>
        <span className="mark mark-unsupported mt-4" aria-label="Not supported by the cited source">!</span>
        <p className="mt-3 text-ink-soft">
          A suit for specific performance may be filed within twelve years of the agreement.{" "}
          <span className="cite">Limitation Act, 1963, Sch, art 54</span>
          <span className="mt-1 block font-sans text-[13px] text-unsupported">
            Not supported: the cited article allows three years.
          </span>
        </p>
      </div>
      <figcaption className="mt-4 border-t pt-3 text-[13px] text-muted-foreground">
        Every statement is checked against the passage it cites before the brief reaches you.
      </figcaption>
    </figure>
  );
}

export function AuthPage() {
  const { me, meta } = useSession();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/matters";
  if (me) return <Navigate to={from} replace />;

  async function submit(e: FormEvent<HTMLFormElement>, path: string) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      const user = await api<Me>(path, { method: "POST", json: data });
      qc.setQueryData(["me"], user);
      navigate(from, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[1.15fr_1fr]">
      <section className="border-b bg-vellum px-5 py-10 sm:px-12 lg:border-b-0 lg:border-r lg:py-16">
        <div className="flex items-center gap-2.5 text-ink">
          <Logo />
          <span className="font-serif text-xl font-semibold">Precedent</span>
        </div>
        <h1 className="mt-12 max-w-[18ch] font-serif text-4xl font-semibold leading-[1.12] tracking-tight text-ink sm:text-5xl">
          Research briefs you can check line by line.
        </h1>
        <p className="mt-5 max-w-[52ch] text-[1.05rem] text-ink-soft">
          Describe the facts of a matter. Precedent argues both sides from legislation and the judgments your firm
          holds, then shows you exactly which section or paragraph supports each point.
        </p>
        <Specimen />
      </section>

      <section className="flex items-start justify-center px-5 py-10 sm:px-12 lg:items-center">
        <div className="w-full max-w-sm">
          <Tabs defaultValue="signin" onValueChange={() => setError("")}>
            <TabsList className="mb-6 grid w-full grid-cols-2">
              <TabsTrigger value="signin">Sign in</TabsTrigger>
              <TabsTrigger value="signup" disabled={meta && !meta.signup}>
                Create firm account
              </TabsTrigger>
            </TabsList>
            <TabsContent value="signin">
              <form className="grid gap-4" onSubmit={(e) => submit(e, "/auth/login")}>
                <Field id="email" label="Work email" type="email" autoComplete="email" spellCheck={false} required />
                <Field id="password" label="Password" type="password" autoComplete="current-password" required />
                {error ? <p role="alert" className="text-sm text-unsupported">{error}</p> : null}
                <Button type="submit" size="lg" className="mt-1 h-10" disabled={busy}>
                  {busy ? "Signing in…" : "Sign in"}
                </Button>
              </form>
            </TabsContent>
            <TabsContent value="signup">
              <form className="grid gap-4" onSubmit={(e) => submit(e, "/auth/signup")}>
                <Field id="firm_name" label="Firm or chambers" autoComplete="organization" required />
                <Field id="name" label="Your name" autoComplete="name" required />
                <Field id="email" label="Work email" type="email" autoComplete="email" required />
                <Field
                  id="password"
                  label="Password"
                  type="password"
                  autoComplete="new-password"
                  hint="At least 10 characters, with upper- and lower-case letters and a number."
                  required
                />
                {error ? <p role="alert" className="text-sm text-unsupported">{error}</p> : null}
                <Button type="submit" size="lg" className="mt-1 h-10" disabled={busy}>
                  {busy ? "Creating account…" : "Create account"}
                </Button>
                <p className="text-xs text-muted-foreground">
                  You become the firm's administrator and can add colleagues afterwards.
                </p>
              </form>
            </TabsContent>
          </Tabs>
          <p className="mt-10 text-xs leading-relaxed text-muted-foreground">
            Precedent prepares research for a qualified lawyer to review. It does not give legal advice.
          </p>
        </div>
      </section>
    </div>
  );
}
