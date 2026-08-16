import { createClient, type NeonPostgrestClient } from "@neondatabase/neon-js";
import { getApiAuthKey } from "./apiAuth";

// ============================================================================
// Neon Database & Auth Configuration
// Project / Application Name: vibe-box
// ============================================================================

export const NEON_APP_NAME = "vibe-box";

export const NEON_DATA_API_URL =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_NEON_DATA_API_URL) ||
  "https://ep-young-cherry-atuvqj2f.apirest.c-9.us-east-1.aws.neon.tech/neondb/rest/v1";

export const NEON_AUTH_URL =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_NEON_AUTH_URL) ||
  "https://ep-young-cherry-atuvqj2f.neonauth.c-9.us-east-1.aws.neon.tech/neondb/auth";

export const NEON_JWKS_URL =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_NEON_JWKS_URL) ||
  "https://ep-young-cherry-atuvqj2f.neonauth.c-9.us-east-1.aws.neon.tech/neondb/auth/.well-known/jwks.json";

export const NEON_JWT_STORAGE_KEY = "vibe_neon_jwt_token";

// Dynamic token provider (e.g. Clerk, Auth0, Supabase, Neon Auth, Firebase, or custom OAuth)
export type TokenGetter = () => Promise<string | null> | string | null;

let customTokenProvider: TokenGetter | null = null;

/**
 * Register a custom Identity Provider token getter (Clerk, Auth0, etc.)
 *
 * @example
 * ```ts
 * import { setCustomTokenProvider } from "@/lib/neon";
 *
 * // Example with Clerk:
 * setCustomTokenProvider(async () => {
 *   return await window.Clerk?.session?.getToken();
 * });
 *
 * // Example with Auth0:
 * setCustomTokenProvider(async () => {
 *   return await auth0Client.getTokenSilently();
 * });
 * ```
 */
export function setCustomTokenProvider(provider: TokenGetter | null): void {
  customTokenProvider = provider;
}

/**
 * Manually store or clear a JWT token in localStorage for Neon Data API operations
 */
export function setStoredNeonJWT(token: string | null): void {
  if (typeof window === "undefined") return;
  const trimmed = token?.trim();
  if (trimmed) {
    localStorage.setItem(NEON_JWT_STORAGE_KEY, trimmed);
  } else {
    localStorage.removeItem(NEON_JWT_STORAGE_KEY);
  }
}

/**
 * Get current stored JWT from local storage if available
 */
export function getStoredNeonJWT(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(NEON_JWT_STORAGE_KEY);
}

/**
 * Clear stored Neon JWT
 */
export function clearStoredNeonJWT(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(NEON_JWT_STORAGE_KEY);
}

/**
 * Core token retriever supplied to @neondatabase/neon-js.
 * This runs before every database query to ensure all requests
 * carry the valid, current JWT validated by Neon's JWKS endpoint.
 *
 * Retrieval priority:
 * 1. Active registered Identity Provider (Clerk / Auth0 / custom provider)
 * 2. Dedicated stored Neon JWT (`vibe_neon_jwt_token`)
 * 3. App session API key / JWT (`vibe_trading_api_auth_key`)
 */
export async function getNeonAuthToken(): Promise<string | null> {
  // 1. Check custom identity provider callback
  if (customTokenProvider) {
    try {
      const token = await customTokenProvider();
      if (token && typeof token === "string" && token.trim()) {
        return token.trim();
      }
    } catch (err) {
      console.warn("[Neon] Identity provider token retrieval warning:", err);
    }
  }

  // 2. Check local dedicated Neon JWT storage
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem(NEON_JWT_STORAGE_KEY);
    if (stored && stored.trim()) {
      return stored.trim();
    }

    // 3. Fallback to app-level API Auth key if configured
    const apiKey = getApiAuthKey();
    if (apiKey && apiKey.trim()) {
      return apiKey.trim();
    }
  }

  return null;
}

/**
 * Neon Data API Client instance initialized with the dynamic `getToken` hook.
 * All queries automatically attach the JWT as a Bearer token so Neon Data API
 * validates it against the configured JWKS URL and enforces Postgres Row-Level Security (RLS).
 *
 * @example
 * ```ts
 * import { neon } from "@/lib/neon";
 *
 * // Read rows governed by RLS
 * const { data, error } = await neon.from("user_strategies").select("*");
 *
 * // Insert row authenticated as current user
 * const { data: inserted, error: insertErr } = await neon
 *   .from("user_orders")
 *   .insert([{ symbol: "BTC-USDT", side: "BUY", size: 0.1 }]);
 * ```
 */
export const neon: NeonPostgrestClient<any, "public"> = createClient({
  dataApi: {
    url: NEON_DATA_API_URL,
    getToken: getNeonAuthToken,
  },
});

/**
 * Diagnostics helper to verify Neon Data API endpoint availability and authentication health
 */
export async function checkNeonConnection(): Promise<{
  connected: boolean;
  status: string;
  authenticated: boolean;
  dataApiUrl: string;
  authUrl: string;
  jwksUrl: string;
  hasToken: boolean;
}> {
  const token = await getNeonAuthToken();
  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${NEON_DATA_API_URL}/`, {
      method: "GET",
      headers,
    });

    const isConnected = response.ok || response.status === 401 || response.status === 404;

    return {
      connected: isConnected,
      status: `HTTP ${response.status} ${response.statusText || "OK"}`,
      authenticated: Boolean(token && (response.ok || response.status !== 401)),
      dataApiUrl: NEON_DATA_API_URL,
      authUrl: NEON_AUTH_URL,
      jwksUrl: NEON_JWKS_URL,
      hasToken: Boolean(token),
    };
  } catch (error) {
    return {
      connected: false,
      status: error instanceof Error ? error.message : "Connection failed",
      authenticated: false,
      dataApiUrl: NEON_DATA_API_URL,
      authUrl: NEON_AUTH_URL,
      jwksUrl: NEON_JWKS_URL,
      hasToken: Boolean(token),
    };
  }
}

export default neon;
