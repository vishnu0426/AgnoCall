import { NextResponse, type NextRequest } from "next/server";

/**
 * Page gate: anyone without a valid sign-in is sent to /login first (and returned to the page they asked
 * for afterwards). The session is the `forms_session` cookie the sign-in page sets. The API is asked
 * whether the token is genuine (GET /auth/me), so a forged or tampered cookie does not get past here; the
 * API also checks the token on every data request, so this gate is only the first line.
 */
const COOKIE = "forms_session";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
const CACHE_MS = 30_000;

// token -> when it was last confirmed. Keeps navigation fast: one check per token every 30 s.
const confirmed = new Map<string, number>();

function expired(token: string): boolean {
  try {
    const part = token.split(".")[1];
    const exp = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/"))).exp;
    return typeof exp !== "number" || exp * 1000 <= Date.now();
  } catch {
    return true;
  }
}

/** true = valid, false = rejected by the API, null = the API could not be reached. */
async function apiAccepts(token: string): Promise<boolean | null> {
  const at = confirmed.get(token);
  if (at && Date.now() - at < CACHE_MS) return true;
  try {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (res.ok) {
      if (confirmed.size > 500) confirmed.clear();
      confirmed.set(token, Date.now());
      return true;
    }
    if (res.status === 401 || res.status === 403) return false;
    return null;
  } catch {
    return null;
  }
}

export async function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (pathname === "/login" || pathname.startsWith("/login/")) return NextResponse.next();

  const token = req.cookies.get(COOKIE)?.value;
  let ok = false;
  if (token && !expired(token)) {
    // If the API is down, let the page load: it shows "can't reach the API" instead of bouncing to sign-in.
    ok = (await apiAccepts(token)) !== false;
  }
  if (ok) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (pathname !== "/") url.searchParams.set("next", pathname + search);
  if (token) url.searchParams.set("reason", "expired");
  const res = NextResponse.redirect(url);
  if (token) res.cookies.set(COOKIE, "", { path: "/", maxAge: 0 });
  return res;
}

export const config = {
  // Everything except Next internals, static files and the public form-fill links.
  matcher: ["/((?!_next/|api/|favicon|forms/f/|.*\\.[a-zA-Z0-9]+$).*)"],
};
