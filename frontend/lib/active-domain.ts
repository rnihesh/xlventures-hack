// Shared source of truth for the active domain pack.
//
// There is no backend endpoint to persist the active pack, so the choice lives
// in localStorage and is broadcast via a custom event. The Domains page writes
// it ("Make active") and the Run page reads it as its default domain, so the
// active pack visibly drives what a run defaults to. Customer Success is the
// flagship, so it is the default when nothing has been chosen yet.

export const ACTIVE_DOMAIN_KEY = "aperture-active-domain";
export const ACTIVE_DOMAIN_EVENT = "aperture:active-domain";
export const DEFAULT_ACTIVE_DOMAIN = "customer_success";

export function getActiveDomain(): string {
  if (typeof window === "undefined") return DEFAULT_ACTIVE_DOMAIN;
  try {
    return localStorage.getItem(ACTIVE_DOMAIN_KEY) || DEFAULT_ACTIVE_DOMAIN;
  } catch {
    return DEFAULT_ACTIVE_DOMAIN;
  }
}

export function setActiveDomain(key: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(ACTIVE_DOMAIN_KEY, key);
    window.dispatchEvent(
      new CustomEvent(ACTIVE_DOMAIN_EVENT, { detail: key }),
    );
  } catch {
    /* storage unavailable; selection still applies for the session */
  }
}
