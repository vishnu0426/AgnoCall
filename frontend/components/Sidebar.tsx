"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { BarChart3, ClipboardCheck, ClipboardList, LayoutDashboard, LogIn, LogOut, PhoneCall, Settings, ShieldCheck, Users } from "lucide-react";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/calls", label: "Calls", icon: PhoneCall },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/compliance", label: "Compliance", icon: ShieldCheck },
  { href: "/calibration", label: "Calibration", icon: ClipboardCheck },
  { href: "/agents", label: "Agents", icon: Users },
  { href: "/forms", label: "Forms", icon: ClipboardList },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [user, setUser] = useState<string | null>(null);
  useEffect(() => {
    try {
      setUser(window.localStorage.getItem("forms_user"));
    } catch {
      setUser(null);
    }
  }, [pathname]);

  function signOut() {
    try {
      window.localStorage.removeItem("forms_jwt");
      window.localStorage.removeItem("forms_user");
    } catch {
      /* storage unavailable */
    }
    document.cookie = "forms_session=; path=/; max-age=0";
    setUser(null);
    window.location.href = "/login";
  }

  return (
    <aside className="w-60 shrink-0 border-r border-hairline bg-panel/60 flex flex-col sticky top-0 h-screen self-start overflow-y-auto">
      <div className="px-5 py-6 flex items-center gap-2.5">
        <WaveMark />
        <div className="font-display font-semibold text-[15px] tracking-tight">
          AgnoCall
        </div>
      </div>

      <nav className="px-3 flex flex-col gap-0.5 mt-2">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-[13.5px] font-medium transition-colors ${
                active
                  ? "bg-panelRaised text-ink"
                  : "text-muted hover:text-ink hover:bg-panelRaised/60"
              }`}
            >
              <Icon className="w-[15px] h-[15px]" strokeWidth={2} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto px-3 pb-2">
        {user ? (
          <button
            onClick={signOut}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] text-muted hover:text-ink hover:bg-panelRaised/60"
            title="Sign out"
          >
            <LogOut className="w-[15px] h-[15px]" /> <span className="truncate">{user} · Sign out</span>
          </button>
        ) : (
          <Link
            href="/login"
            className="flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] text-muted hover:text-ink hover:bg-panelRaised/60"
          >
            <LogIn className="w-[15px] h-[15px]" /> Sign in
          </Link>
        )}
      </div>

      <div className="px-5 py-5 text-[11px] text-faint font-mono leading-relaxed">
        On-prem · self-hosted
        <br />
        deployment: hybrid
      </div>
    </aside>
  );
}

function WaveMark() {
  // The waveform is the signature element throughout the product — this is
  // its smallest expression, a static "at rest" bar pattern used as a mark.
  const heights = [4, 9, 14, 8, 16, 6, 11, 5];
  return (
    <svg width="22" height="18" viewBox="0 0 22 18" fill="none">
      {heights.map((h, i) => (
        <rect
          key={i}
          x={i * 2.7}
          y={9 - h / 2}
          width="1.6"
          height={h}
          rx="0.8"
          fill={i % 3 === 0 ? "#2F6FED" : "#6C7488"}
        />
      ))}
    </svg>
  );
}
