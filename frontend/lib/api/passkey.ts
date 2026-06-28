// Typed client for passkey (WebAuthn) login and registration.
//
// The backend drives a cookie-based session, so every request sends
// credentials:"include". Login is a two-step handshake: ask for assertion
// options (which carry a server-side `handle`), run the authenticator via
// @simplewebauthn/browser, then post the assertion plus the handle back to
// verify. Registration mirrors that flow but requires an authenticated session.

import {
  startAuthentication,
  startRegistration,
  type AuthenticationResponseJSON,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
  type RegistrationResponseJSON,
} from "@simplewebauthn/browser";

import { API_BASE } from "@/lib/api";
import { authHeaders } from "@/lib/auth";
import type { AuthOrg, AuthUser } from "@/lib/auth-context";

// The /login/verify response mirrors POST /auth/login: the signed-in user and
// their org. The session cookie is set by the same response.
export interface PasskeyLoginResult {
  user: AuthUser;
  org: AuthOrg;
}

// A registered credential as returned by GET /auth/passkey.
export interface PasskeySummary {
  credential_id: string;
  label: string | null;
  created_at: string;
  last_used_at: string | null;
}

// The /login/options payload: the assertion options plus an opaque `handle`
// the backend uses to correlate the challenge on verify.
type LoginOptionsResponse = PublicKeyCredentialRequestOptionsJSON & {
  handle: string;
};

// Whether this browser exposes the WebAuthn API. Guards the UI so the passkey
// button only renders where it can actually work.
export function isPasskeySupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined"
  );
}

async function postJson<T>(
  path: string,
  body: unknown,
  errorMessage: string,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      credentials: "include",
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw new Error("Could not reach the server. Check your connection.");
  }
  if (!res.ok) {
    let detail = errorMessage;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      /* keep the default message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

// Map an authenticator/WebAuthn failure to a friendly, user-facing message.
function friendlyWebAuthnError(err: unknown, fallback: string): Error {
  const name = (err as { name?: string }).name;
  if (name === "NotAllowedError" || name === "AbortError") {
    return new Error("Passkey request was cancelled or timed out.");
  }
  if (name === "InvalidStateError") {
    return new Error("This device already has a passkey for your account.");
  }
  if (err instanceof Error && err.message) {
    return err;
  }
  return new Error(fallback);
}

/**
 * Sign in with a passkey. Pass `email` to target a specific account's
 * credentials, or omit it for a usernameless / discoverable passkey. Resolves
 * to the signed-in user and org once the session cookie is set; throws a
 * friendly Error if the user cancels or the credential is not recognized.
 */
export async function loginWithPasskey(
  email?: string,
): Promise<PasskeyLoginResult> {
  const options = await postJson<LoginOptionsResponse>(
    "/auth/passkey/login/options",
    email ? { email } : {},
    "Could not start passkey sign-in.",
  );

  const { handle, ...optionsJSON } = options;

  let credential: AuthenticationResponseJSON;
  try {
    credential = await startAuthentication({ optionsJSON });
  } catch (err) {
    throw friendlyWebAuthnError(err, "Passkey sign-in failed.");
  }

  return postJson<PasskeyLoginResult>(
    "/auth/passkey/login/verify",
    { credential, handle },
    "That passkey was not recognized.",
  );
}

/**
 * Register a new passkey for the signed-in user. Requires an active session
 * cookie. Optionally label the credential (for example the device name).
 * Throws a friendly Error on cancel or failure.
 */
export async function registerPasskey(label?: string): Promise<void> {
  const optionsJSON = await postJson<PublicKeyCredentialCreationOptionsJSON>(
    "/auth/passkey/register/options",
    {},
    "Could not start passkey registration.",
  );

  let credential: RegistrationResponseJSON;
  try {
    credential = await startRegistration({ optionsJSON });
  } catch (err) {
    throw friendlyWebAuthnError(err, "Passkey registration failed.");
  }

  await postJson<{ ok: true }>(
    "/auth/passkey/register/verify",
    label ? { credential, label } : { credential },
    "Could not save your passkey.",
  );
}

/**
 * List the signed-in user's registered passkeys. Returns an empty array when
 * the backend is unreachable so the settings section renders cleanly offline.
 */
export async function listPasskeys(
  signal?: AbortSignal,
): Promise<PasskeySummary[]> {
  try {
    const res = await fetch(`${API_BASE}/auth/passkey`, {
      headers: authHeaders({ Accept: "application/json" }),
      credentials: "include",
      cache: "no-store",
      signal,
    });
    if (!res.ok) return [];
    return (await res.json()) as PasskeySummary[];
  } catch {
    return [];
  }
}
