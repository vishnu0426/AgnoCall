"use client";

import { FormEvent, KeyboardEvent, Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, ClipboardCheck, Eye, EyeOff, Info, Loader2, ShieldAlert, UserCheck } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { loginFailureMessage, safeNext } from "@/lib/login";
import BrandMark from "@/components/login/BrandMark";
import ProductPreview from "@/components/login/ProductPreview";
import WaveBackdrop from "@/components/login/WaveBackdrop";

const REQUEST_TIMEOUT_MS = 15_000;

const POINTS = [
  { icon: ClipboardCheck, text: "Automatic QA scoring against your own scorecards" },
  { icon: ShieldAlert, text: "Compliance flags that quote the exact line" },
  { icon: UserCheck, text: "Human review and calibration to keep the AI honest" },
];

const INPUT =
  "block h-11 w-full rounded-lg border border-[#C4CBD9] bg-white px-3.5 text-[14px] text-ink placeholder-[#8B93A7] " +
  "transition-colors hover:border-[#9AA4BA] focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 " +
  "disabled:bg-panelRaised disabled:text-faint";

/**
 * Sign in with the Forms account (POST /auth/login). The token is stored in this browser and sent with API
 * requests so the server can tell who is enabling or running AI evaluation.
 */
function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const expired = params.get("reason") === "expired";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refocusPassword, setRefocusPassword] = useState(false);
  // False until React has taken over the page. Before that a submit would be a plain browser form
  // submission, which would put the username and password in the address bar, history and server logs.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const userRef = useRef<HTMLInputElement>(null);
  const passRef = useRef<HTMLInputElement>(null);

  // Reaching this page means there is no valid session (the page gate sent us here), so drop any
  // leftover sign-in data from an earlier visit.
  useEffect(() => {
    try {
      window.localStorage.removeItem("forms_jwt");
      window.localStorage.removeItem("forms_user");
    } catch {
      /* storage unavailable */
    }
  }, []);

  // After a failed attempt put the cursor back in the password field. It has to wait until the field is
  // enabled again: a disabled input silently ignores focus().
  useEffect(() => {
    if (refocusPassword && !busy) {
      passRef.current?.focus();
      setRefocusPassword(false);
    }
  }, [refocusPassword, busy]);

  const watchCapsLock = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState?.("CapsLock") ?? false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const name = username.trim();
    if (!name || !password) {
      setError(!name ? "Enter your username." : "Enter your password.");
      (!name ? userRef : passRef).current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: name, password }),
        signal: controller.signal,
      });
      if (!res.ok) {
        setError(loginFailureMessage(res.status));
        setPassword("");
        setRefocusPassword(true);
        return;
      }
      const data = await res.json();
      window.localStorage.setItem("forms_jwt", data.token);
      window.localStorage.setItem("forms_user", data.user?.username ?? name);
      // The page gate (middleware.ts) reads this cookie; it expires with the token.
      const exp = (() => {
        try {
          return JSON.parse(atob(String(data.token).split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))).exp;
        } catch {
          return null;
        }
      })();
      const maxAge = typeof exp === "number" ? Math.max(0, Math.floor(exp - Date.now() / 1000)) : 8 * 3600;
      document.cookie = `forms_session=${data.token}; path=/; max-age=${maxAge}; samesite=lax`;
      router.replace(next);
      router.refresh();
    } catch {
      setError(loginFailureMessage(null, controller.signal.aborted));
      setRefocusPassword(true);
    } finally {
      clearTimeout(timer);
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-[1.1fr_1fr]">
      {/* ---- Brand panel (large screens) ---- */}
      <aside
        className="relative hidden overflow-hidden text-white lg:flex lg:flex-col lg:justify-between lg:px-14 lg:py-12"
        style={{
          background:
            "radial-gradient(900px 520px at 12% -5%, rgba(47,111,237,0.55), transparent 60%)," +
            "radial-gradient(760px 520px at 105% 105%, rgba(29,79,191,0.55), transparent 55%)," +
            "linear-gradient(160deg, #0C1D44 0%, #08122B 100%)",
        }}
      >
        <WaveBackdrop className="pointer-events-none absolute inset-x-0 bottom-0 h-[58%] w-full opacity-[0.34]" />

        <div className="relative flex items-center gap-2.5">
          <BrandMark light size={1.15} />
          <span className="font-display text-[17px] font-semibold tracking-tight">AgnoCall</span>
        </div>

        <div className="relative max-w-[520px]">
          <p className="mb-3 text-[12px] font-medium uppercase tracking-[0.14em] text-[#8DB2FF]">AI call analysis</p>
          <h2 className="font-display text-[40px] font-semibold leading-[1.1] tracking-tight [text-wrap:balance] xl:text-[44px]">
            Every call, scored and explained.
          </h2>
          <p className="mt-4 text-[15.5px] leading-relaxed text-[#CAD6F2]">
            AgnoCall listens to your recorded calls and gives QA teams scores, compliance flags and coaching insight,
            each tied to the exact words in the conversation.
          </p>
          <ul className="mt-7 space-y-3.5">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-[14.5px] text-[#E4EBFB]">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/10 ring-1 ring-white/15">
                  <Icon className="h-4 w-4 text-[#8DB2FF]" strokeWidth={2} />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>

        {/* The preview card needs height: on short screens (e.g. 1366x768) it is dropped so the page never scrolls. */}
        <div className="relative hidden [@media(min-height:840px)]:block">
          <ProductPreview />
        </div>
      </aside>

      {/* ---- Sign-in panel ---- */}
      <main className="flex flex-col px-6 py-8 sm:px-12">
        {/* Phones and tablets: the big brand panel is hidden, so keep the brand in a slim dark header. */}
        <div
          className="-mx-6 -mt-8 mb-10 flex items-center gap-2.5 px-6 py-5 text-white sm:-mx-12 sm:px-12 lg:hidden"
          style={{ background: "linear-gradient(160deg, #0C1D44 0%, #08122B 100%)" }}
        >
          <BrandMark light size={1.15} />
          <span className="font-display text-[17px] font-semibold tracking-tight">AgnoCall</span>
        </div>

        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center">
          <h1 className="font-display text-[28px] font-semibold tracking-tight text-ink">Sign in</h1>
          <p className="mt-1.5 text-[14.5px] text-muted">Welcome back. Enter your details to continue.</p>

          {expired && (
            <div role="status" className="mt-6 flex gap-2.5 rounded-lg border border-[#9C6510]/30 bg-[#9C6510]/8 px-3.5 py-3 text-[13.5px] text-[#7A4E0C]">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              Your session expired. Please sign in again.
            </div>
          )}

          {/* method="post": even if a plain submission ever slips through, credentials never go in the URL. */}
          <form onSubmit={submit} method="post" noValidate data-ready={ready} className="mt-7 space-y-5">
            <div>
              <label htmlFor="username" className="mb-1.5 block text-[13px] font-medium text-ink">
                Username
              </label>
              <input
                ref={userRef}
                id="username"
                name="username"
                autoFocus
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={busy}
                aria-invalid={!!error && !username.trim()}
                aria-describedby={error ? "login-error" : undefined}
                className={INPUT}
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1.5 block text-[13px] font-medium text-ink">
                Password
              </label>
              <div className="relative">
                <input
                  ref={passRef}
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={watchCapsLock}
                  onKeyUp={watchCapsLock}
                  onBlur={() => setCapsLock(false)}
                  disabled={busy}
                  aria-invalid={!!error && !password}
                  aria-describedby={error ? "login-error" : capsLock ? "caps-hint" : undefined}
                  className={`${INPUT} pr-11`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-lg text-faint hover:text-ink"
                >
                  {showPassword ? <EyeOff className="h-[18px] w-[18px]" /> : <Eye className="h-[18px] w-[18px]" />}
                </button>
              </div>
              {capsLock && (
                <p id="caps-hint" className="mt-1.5 text-[12.5px] text-[#9C6510]">
                  Caps Lock is on.
                </p>
              )}
            </div>

            {error && (
              <div
                id="login-error"
                role="alert"
                className="flex gap-2.5 rounded-lg border border-bad/30 bg-bad/5 px-3.5 py-3 text-[13.5px] text-bad"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy || !ready}
              aria-busy={busy}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent text-[14.5px] font-medium text-white shadow-sm transition-colors hover:bg-accentDim focus-visible:outline-offset-2 disabled:cursor-wait disabled:bg-accentDim"
            >
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </button>
          </form>

          <p className="mt-7 text-center text-[13px] text-faint [text-wrap:balance]">
            Forgot your password? Ask your administrator to reset it.
          </p>
        </div>

        <p className="mt-10 text-center text-[12px] text-faint">AgnoCall · AI call analysis</p>
      </main>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary so the page can still be built statically.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
