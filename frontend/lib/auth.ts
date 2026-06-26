// Optional bearer auth. When NEXT_PUBLIC_APP_TOKEN is set, every backend
// request carries Authorization: Bearer <token> to satisfy the backend's
// APP_TOKEN gate. A blank token leaves requests unauthenticated (open mode),
// which matches the backend default of an open API when APP_TOKEN is unset.
export const APP_TOKEN = process.env.NEXT_PUBLIC_APP_TOKEN ?? "";

export function authHeaders(
  base: Record<string, string> = {},
): Record<string, string> {
  return APP_TOKEN ? { ...base, Authorization: `Bearer ${APP_TOKEN}` } : base;
}
