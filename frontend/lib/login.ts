/** Pure helpers for the sign-in page (kept free of React so they can be unit-tested). */

/**
 * Where to go after signing in. Only a same-site path is accepted: a `next` value like
 * "https://evil.example" or "//evil.example" would turn the login page into an open redirect used for
 * phishing. Anything else (or a loop back to /login) falls back to the dashboard.
 */
export function safeNext(raw: string | null | undefined): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  if (/[\u0000-\u001f]/.test(raw)) return "/";
  if (raw === "/login" || raw.startsWith("/login?") || raw.startsWith("/login/")) return "/";
  return raw;
}

/**
 * What to tell the person when sign-in fails. A wrong username and a wrong password get the SAME
 * message, so the page cannot be used to find out which usernames exist.
 */
export function loginFailureMessage(status: number | null, timedOut = false): string {
  if (status === 401 || status === 403) return "Wrong username or password.";
  if (status === 429) return "Too many attempts. Wait a minute, then try again.";
  if (status !== null && status >= 500) {
    return "The server had a problem. Try again, or contact your administrator.";
  }
  if (status !== null) return `Sign-in failed (error ${status}).`;
  return timedOut
    ? "The server did not respond in time. Check that the API is running, then try again."
    : "Cannot reach the server. Check your connection and that the API is running.";
}
