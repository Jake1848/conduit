"use client";

/**
 * Conduit Pro — honest, optional license gating for the dashboard's CONVENIENCE
 * features only.
 *
 * ──────────────────────────────────────────────────────────────────────────────
 * WHAT THIS DOES AND DOES NOT DO — read before changing anything:
 *
 *  • This gates ONLY the dashboard's Pro panels (alerts, analytics, multi-instance).
 *  • It has ZERO effect on the open-source SDK, the Core API, or the payment money
 *    path. Those run fully, for free, forever, with NO license check anywhere near
 *    them. An operator with no license still has 100% of the payment functionality.
 *  • Verification is entirely CLIENT-SIDE and OFFLINE: an Ed25519 signature check
 *    against a bundled public key. NO network call. NO phone-home. NO telemetry.
 *  • If the license is missing/invalid/expired, the Pro panels show an "Upgrade"
 *    state — nothing breaks. This is convenience-gating, never core-gating.
 *
 * A license is `base64url(JSON payload) + "." + base64url(ed25519 signature)`,
 * signed offline by the project with the private key matching PRO_PUBLIC_KEY_HEX.
 * ──────────────────────────────────────────────────────────────────────────────
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { createElement } from "react";
import * as ed from "@noble/ed25519";

// The project's license-signing PUBLIC key (Ed25519, hex).
// NOTE: this is a DEV/demo key for the review scaffold. Replace with the project's
// real public key before shipping; keep the matching private key secret.
const PRO_PUBLIC_KEY_HEX =
  "2da043b648ba174036082695d547e393399faf1fa5d20f3d10b58512053a03f2";

const LICENSE_STORAGE_KEY = "conduit_pro_license";

export type ProFeature = "alerts" | "analytics" | "fleet";

export interface License {
  plan: string;
  licensee: string;
  features: ProFeature[];
  issued: string;
  expires: string | null;
  id: string;
}

function b64urlToBytes(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64.padEnd(Math.ceil(b64.length / 4) * 4, "=");
  const bin = atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

/** Verify a license token offline. Returns the License if the signature is valid
 *  and it hasn't expired; otherwise null. Pure crypto — no network. */
export async function verifyLicense(token: string): Promise<License | null> {
  try {
    // Exactly two segments — reject malleable tokens like "payload.sig.junk".
    const parts = token.trim().split(".");
    if (parts.length !== 2) return null;
    const [payloadB64, sigB64] = parts;
    if (!payloadB64 || !sigB64) return null;
    const payloadBytes = b64urlToBytes(payloadB64);
    const payloadStr = new TextDecoder().decode(payloadBytes);
    const sig = b64urlToBytes(sigB64);
    const pub = hexToBytes(PRO_PUBLIC_KEY_HEX);
    // The signed message is the exact payload bytes (so re-parsing can't change them).
    const ok = await ed.verifyAsync(sig, payloadBytes, pub);
    if (!ok) return null;
    const lic = JSON.parse(payloadStr) as License;
    // Fail closed: a present-but-unparseable `expires` must not read as never-expiring.
    if (lic.expires != null) {
      const exp = new Date(lic.expires).getTime();
      if (Number.isNaN(exp) || exp < Date.now()) return null;
    }
    if (!Array.isArray(lic.features)) return null;
    return lic;
  } catch {
    return null;
  }
}

interface ProState {
  /** true iff a valid, unexpired license is loaded. */
  pro: boolean;
  license: License | null;
  loading: boolean;
  /** does the current license grant a specific feature? */
  has: (f: ProFeature) => boolean;
  /** verify + store a pasted license token; returns whether it was valid. */
  setLicenseToken: (token: string) => Promise<boolean>;
  clearLicense: () => void;
}

const ProCtx = createContext<ProState | null>(null);

export function ProProvider({ children }: { children: ReactNode }) {
  const [license, setLicense] = useState<License | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const stored = typeof window !== "undefined" ? localStorage.getItem(LICENSE_STORAGE_KEY) : null;
    if (!stored) {
      setLoading(false);
      return;
    }
    verifyLicense(stored).then((lic) => {
      if (cancelled) return;
      setLicense(lic);
      setLoading(false);
      // A stored-but-now-invalid (e.g. expired) license is cleared silently.
      if (!lic) localStorage.removeItem(LICENSE_STORAGE_KEY);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const setLicenseToken = useCallback(async (token: string): Promise<boolean> => {
    const lic = await verifyLicense(token);
    if (!lic) return false;
    localStorage.setItem(LICENSE_STORAGE_KEY, token.trim());
    setLicense(lic);
    return true;
  }, []);

  const clearLicense = useCallback(() => {
    localStorage.removeItem(LICENSE_STORAGE_KEY);
    setLicense(null);
  }, []);

  const has = useCallback(
    (f: ProFeature) => !!license && license.features.includes(f),
    [license],
  );

  const value: ProState = {
    pro: !!license,
    license,
    loading,
    has,
    setLicenseToken,
    clearLicense,
  };
  return createElement(ProCtx.Provider, { value }, children);
}

export function usePro(): ProState {
  const ctx = useContext(ProCtx);
  if (!ctx) throw new Error("usePro must be used within <ProProvider>");
  return ctx;
}
