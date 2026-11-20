import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, formatDate } from "@/lib/api";
import { useSession } from "@/lib/session";

type Member = { id: number; name: string; email: string; role: string; active: boolean; last_login: string | null };
type AuditRow = { at: string; user: string | null; action: string; detail: string };

const ACTIONS: Record<string, string> = {
  "firm.created": "Created the firm account", "user.login": "Signed in", "user.password_changed": "Changed password",
  "team.added": "Added a colleague", "team.removed": "Removed a colleague", "firm.updated": "Changed firm settings",
  "matter.created": "Created a matter", "matter.deleted": "Deleted a matter", "run.started": "Prepared a brief",
  "run.exported": "Exported a brief", "library.uploaded": "Uploaded a judgment", "library.deleted": "Removed a judgment",
};

function AddMember() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<{ email: string; temporary_password: string } | null>(null);
  const [error, setError] = useState("");
  const add = useMutation({
    mutationFn: (body: Record<string, FormDataEntryValue>) =>
      api<{ email: string; temporary_password: string }>("/team", { method: "POST", json: body }),
    onSuccess: (r) => {
      setCreated(r);
      qc.invalidateQueries({ queryKey: ["team"] });
    },
    onError: (e) => setError((e as Error).message),
  });
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    add.mutate({ ...Object.fromEntries(new FormData(e.currentTarget)), role: "member" });
  }
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setCreated(null); }}>
      <DialogTrigger asChild>
        <Button variant="outline"><UserPlus /> Add colleague</Button>
      </DialogTrigger>
      <DialogContent>
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Account created</DialogTitle>
              <DialogDescription>
                Send these details to {created.email} privately. They will be asked to choose their own password when
                they first sign in. This password is not shown again.
              </DialogDescription>
            </DialogHeader>
            <p className="rounded-md border bg-vellum px-3 py-2 font-semibold tracking-wide text-ink select-all">{created.temporary_password}</p>
            <DialogFooter>
              <Button onClick={() => { void navigator.clipboard?.writeText(created.temporary_password); toast.success("Password copied"); }}>
                Copy password
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Add a colleague</DialogTitle>
              <DialogDescription>They join {"your firm"} and can see its matters and library.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-1.5"><Label htmlFor="m-name">Name</Label><Input id="m-name" name="name" required /></div>
            <div className="grid gap-1.5"><Label htmlFor="m-email">Work email</Label><Input id="m-email" name="email" type="email" required /></div>
            {error ? <p role="alert" className="text-sm text-unsupported">{error}</p> : null}
            <DialogFooter><Button type="submit" disabled={add.isPending}>Create account</Button></DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ChangePassword({ forced }: { forced: boolean }) {
  const { refresh } = useSession();
  const [error, setError] = useState("");
  const change = useMutation({
    mutationFn: (body: Record<string, FormDataEntryValue>) => api("/auth/password", { method: "POST", json: body }),
    onSuccess: () => { toast.success("Password changed"); refresh(); },
    onError: (e) => setError((e as Error).message),
  });
  return (
    <form id="password" className="grid max-w-sm gap-4" onSubmit={(e) => {
      e.preventDefault();
      setError("");
      change.mutate(Object.fromEntries(new FormData(e.currentTarget)));
      e.currentTarget.reset();
    }}>
      {forced ? <p className="rounded-md bg-tape-wash px-3 py-2 text-sm text-ink">Choose your own password to finish setting up your account.</p> : null}
      <div className="grid gap-1.5"><Label htmlFor="cur">Current password</Label><Input id="cur" name="current_password" type="password" autoComplete="current-password" required /></div>
      <div className="grid gap-1.5"><Label htmlFor="new">New password</Label><Input id="new" name="new_password" type="password" autoComplete="new-password" required /></div>
      {error ? <p role="alert" className="text-sm text-unsupported">{error}</p> : null}
      <Button type="submit" variant="outline" className="justify-self-start" disabled={change.isPending}>Change password</Button>
    </form>
  );
}

export function TeamPage() {
  const { me, refresh } = useSession();
  const qc = useQueryClient();
  const isAdmin = me?.role === "admin";
  const team = useQuery({ queryKey: ["team"], queryFn: () => api<Member[]>("/team") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api<AuditRow[]>("/audit"), enabled: isAdmin });
  const firm = useMutation({
    mutationFn: (body: { include_summaries: boolean }) => api("/firm", { method: "PATCH", json: body }),
    onSuccess: () => { refresh(); toast.success("Library setting saved"); },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/team/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["team"] }),
  });
  if (!me) return null;

  return (
    <>
      <PageHeader title={me.firm} lede="People, library settings and the record of what has been done in your account.">
        {isAdmin ? <AddMember /> : null}
      </PageHeader>
      <div className="grid max-w-5xl gap-12 px-4 py-8 sm:px-8">
        {me.must_change_password ? <ChangePassword forced /> : null}

        <section>
          <h2 className="font-serif text-xl font-semibold text-ink">People</h2>
          <ul className="mt-4 divide-y rounded-md border bg-card">
            {(team.data ?? []).map((u) => (
              <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{u.name}{u.id === me.id ? <span className="font-normal text-muted-foreground"> (you)</span> : null}</p>
                  <p className="truncate text-sm text-muted-foreground">
                    {u.email}. {u.role === "admin" ? "Administrator" : "Member"}.{" "}
                    {u.active ? (u.last_login ? `Last signed in ${formatDate(u.last_login)}` : "Has not signed in yet") : "Removed"}
                  </p>
                </div>
                {isAdmin && u.active && u.id !== me.id ? (
                  <Button variant="ghost" size="sm" onClick={() => {
                    if (window.confirm(`Remove ${u.name}? They will be signed out and can no longer use your firm's account.`)) remove.mutate(u.id);
                  }}>Remove</Button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>

        {isAdmin ? (
          <section>
            <h2 className="font-serif text-xl font-semibold text-ink">Library</h2>
            <div className="mt-4 flex max-w-2xl items-start justify-between gap-6 rounded-md border bg-card px-4 py-4">
              <div>
                <Label htmlFor="summaries" className="text-[15px] font-semibold">Use leading-case summaries</Label>
                <p className="mt-1 text-sm text-muted-foreground">
                  Fifty paraphrased summaries of classic tort and contract cases. Useful for orientation, but they are
                  not the judgments, so briefs mark them as summaries. Turn this off to cite only legislation and your
                  uploaded judgments.
                </p>
              </div>
              <Switch id="summaries" checked={me.include_summaries} onCheckedChange={(v) => firm.mutate({ include_summaries: v })} />
            </div>
          </section>
        ) : null}

        {!me.must_change_password ? (
          <section>
            <h2 className="font-serif text-xl font-semibold text-ink">Your password</h2>
            <div className="mt-4"><ChangePassword forced={false} /></div>
          </section>
        ) : null}

        {isAdmin ? (
          <section>
            <h2 className="font-serif text-xl font-semibold text-ink">Activity</h2>
            <div className="mt-4 overflow-x-auto rounded-md border bg-card">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead className="border-b bg-vellum/60 text-[13px] text-muted-foreground">
                  <tr><th className="px-4 py-2 font-semibold">When</th><th className="px-4 py-2 font-semibold">Who</th><th className="px-4 py-2 font-semibold">What</th></tr>
                </thead>
                <tbody>
                  {(audit.data ?? []).slice(0, 60).map((a, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted-foreground">{formatDate(a.at, true)}</td>
                      <td className="px-4 py-2 text-ink-soft">{a.user ?? "—"}</td>
                      <td className="px-4 py-2 text-ink">{ACTIONS[a.action] ?? a.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}
      </div>
    </>
  );
}
