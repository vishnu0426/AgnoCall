import { NextResponse, type NextRequest } from "next/server";

/**
 * Page gate: anyone without a signed-in session is sent to /login first (and returned to the page they
 * asked for afterwards). The session is the `forms_session` cookie the sign-in page sets. Here we only read
 * its expiry; the API checks the token's signature itself. This keeps the screens private, it is not a
 * substitute for protecting the API routes.
 */
const COOKIE = "forms_session";

function validSession(token: string | undefined): boolean {
  if (!token) return false;
  try {
    const part = token.split(".")[1];
    if (!part) return false;
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    const exp = JSON.parse(json).exp;
    return typeof exp !== "number" || exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const session = req.cookies.get(COOKIE)?.value;
  const signedIn = validSession(session);

  if (pathname === "/login" || pathname.startsWith("/login/")) return NextResponse.next();
  if (signedIn) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  if (pathname !== "/") url.searchParams.set("next", pathname + search);
  if (session) url.searchParams.set("reason", "expired");
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except Next internals, static files and public form links.
  matcher: ["/((?!_next/|api/|favicon|fill/|.*\\.[a-zA-Z0-9]+$).*)"],
};
