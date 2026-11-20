import { BookOpen, FolderOpen, LogOut, Menu, Monitor, Moon, Sun, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { useSession, useTheme } from "@/lib/session";

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-7", className)}>
      <rect x="4" y="2.5" width="19" height="25" rx="1.5" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M8 9h11M8 13h11M8 17h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <g transform="rotate(-10 22 22)">
        <rect x="14.5" y="15" width="14" height="13" rx="1.5" fill="var(--card)" stroke="var(--seal)" strokeWidth="2.2" />
        <path d="m18 21.5 2.6 2.6 4.6-5" fill="none" stroke="var(--seal)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

const NAV = [
  { to: "/matters", label: "Matters", icon: FolderOpen },
  { to: "/library", label: "Library", icon: BookOpen },
  { to: "/team", label: "Firm", icon: Users },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {NAV.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-[0.95rem] text-ink-soft transition-colors hover:bg-accent hover:text-ink",
              isActive && "seal-active bg-accent font-semibold text-ink",
            )
          }
        >
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function AccountMenu() {
  const { me, signOut } = useSession();
  const [theme, setTheme] = useTheme();
  const navigate = useNavigate();
  if (!me) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left hover:bg-accent">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-sm font-bold text-paper">
            {me.name.slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold">{me.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{me.firm}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-60">
        <DropdownMenuLabel className="truncate font-normal text-muted-foreground">{me.email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as "light" | "dark" | "system")}>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" /> Match system
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            await signOut();
            navigate("/signin");
          }}
        >
          <LogOut className="size-4" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <a
        href="#main"
        className="sr-only z-50 rounded bg-ink px-3 py-2 text-paper focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-dvh flex-col border-r bg-vellum px-3 py-5 lg:flex">
        <Link to="/matters" className="mb-8 flex items-center gap-2.5 px-3 text-ink">
          <Logo />
          <span className="font-serif text-xl font-semibold tracking-tight">Precedent</span>
        </Link>
        <NavLinks />
        <div className="mt-auto">
          <AccountMenu />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-vellum/95 px-4 backdrop-blur lg:hidden">
        <Link to="/matters" className="flex items-center gap-2 text-ink">
          <Logo className="size-6" />
          <span className="font-serif text-lg font-semibold">Precedent</span>
        </Link>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Open menu">
              <Menu />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="flex w-72 flex-col bg-vellum p-4">
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <div className="mb-6 mt-2 flex items-center gap-2.5 px-3 text-ink">
              <Logo />
              <span className="font-serif text-xl font-semibold">Precedent</span>
            </div>
            <NavLinks onNavigate={() => setOpen(false)} />
            <div className="mt-auto">
              <AccountMenu />
            </div>
          </SheetContent>
        </Sheet>
      </header>

      <main id="main" className="min-w-0">
        {children}
      </main>
    </div>
  );
}

export function PageHeader({ title, children, lede }: { title: string; children?: ReactNode; lede?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 border-b px-4 pb-6 pt-8 sm:flex-row sm:items-end sm:justify-between sm:px-8 lg:pt-12">
      <div className="min-w-0">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-ink sm:text-[2.15rem]">{title}</h1>
        {lede ? <p className="mt-2 max-w-[62ch] text-ink-soft">{lede}</p> : null}
      </div>
      {children ? <div className="flex shrink-0 flex-wrap gap-2">{children}</div> : null}
    </div>
  );
}
