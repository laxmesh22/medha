// Auth0 sign-in (Google or email on Auth0's hosted login page). Supabase accepts Auth0's ID token as a third-party
// provider; an Auth0 post-login Action must add role = 'authenticated' to the ID token (see README).
import { createAuth0Client, type Auth0Client } from "@auth0/auth0-spa-js";

const domain = import.meta.env.VITE_AUTH0_DOMAIN as string | undefined;
const clientId = import.meta.env.VITE_AUTH0_CLIENT_ID as string | undefined;

export const auth0Configured = Boolean(domain && clientId);

let client: Promise<Auth0Client> | null = null;

export function auth0(): Promise<Auth0Client> {
  if (!domain || !clientId) throw new Error("Auth0 is not configured (VITE_AUTH0_DOMAIN, VITE_AUTH0_CLIENT_ID)");
  client ??= createAuth0Client({
    domain,
    clientId,
    authorizationParams: { redirect_uri: window.location.origin, scope: "openid profile email" },
    cacheLocation: "localstorage", // stay signed in across reloads
    useRefreshTokens: true,
  });
  return client;
}

export const GOOGLE_CONNECTION = (import.meta.env.VITE_AUTH0_GOOGLE_CONNECTION as string | undefined) || "google-oauth2";

/** The raw ID token, which Supabase verifies (it carries the role claim). */
export async function idToken(): Promise<string | null> {
  const a = await auth0();
  if (!(await a.isAuthenticated())) return null;
  return (await a.getIdTokenClaims())?.__raw ?? null;
}

let callback: Promise<string | null> | null = null;

/** If the URL is an Auth0 callback, finish it and return where the user was going. The code can be exchanged only
 *  once, so concurrent callers (React StrictMode runs the first load twice) share one exchange. */
export function handleAuth0Redirect(): Promise<string | null> {
  const q = new URLSearchParams(window.location.search);
  if (!(q.has("code") || q.has("error")) || !q.has("state")) return Promise.resolve(null);
  callback ??= (async () => {
    const a = await auth0();
    try {
      const r = await a.handleRedirectCallback<{ returnTo?: string }>();
      return r.appState?.returnTo ?? "/";
    } finally {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  })();
  return callback;
}
