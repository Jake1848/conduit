#!/usr/bin/env node
/**
 * Conduit Pro — offline license minter (project-side tool).
 *
 * This is the COUNTERPART to dashboard/lib/pro.ts: it produces the Ed25519-signed
 * license tokens that the dashboard verifies entirely offline. It gates ONLY the
 * dashboard's convenience panels (alerts / analytics / fleet) — it has no bearing
 * on the open-source SDK, the Core API, or the payment money path.
 *
 * The PRIVATE key is never committed and never bundled. It is read from the
 * CONDUIT_PRO_PRIVATE_KEY env var (or --key). The matching PUBLIC key is the one
 * baked into lib/pro.ts (PRO_PUBLIC_KEY_HEX).
 *
 * Token format (matches verifyLicense in lib/pro.ts exactly):
 *   base64url(JSON payload) + "." + base64url(ed25519 signature over the payload bytes)
 *
 * Usage:
 *   # 1) generate a fresh signing keypair (do this ONCE; keep the private key secret)
 *   node scripts/mint-license.mjs --genkey
 *
 *   # 2) mint a license (private key via env is preferred over --key)
 *   CONDUIT_PRO_PRIVATE_KEY=<hex> node scripts/mint-license.mjs \
 *     --licensee "Acme Corp" \
 *     --features alerts,analytics,fleet \
 *     --plan pro \
 *     --expires 2027-06-14 \
 *     --id lic_0001
 *
 * No network calls. No telemetry. Nothing custodial.
 */
import * as ed from "@noble/ed25519";

function b64url(bytes) {
  return Buffer.from(bytes).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function hexToBytes(hex) {
  const clean = hex.trim().toLowerCase();
  if (!/^[0-9a-f]+$/.test(clean) || clean.length % 2 !== 0) {
    throw new Error("private key must be hex (even length)");
  }
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return out;
}
function bytesToHex(bytes) {
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}
function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
function has(flag) {
  return process.argv.includes(`--${flag}`);
}

async function genkey() {
  const priv = ed.utils.randomSecretKey();
  const pub = await ed.getPublicKeyAsync(priv);
  console.log("# Conduit Pro signing keypair — KEEP THE PRIVATE KEY SECRET.");
  console.log("# Put the PUBLIC key into PRO_PUBLIC_KEY_HEX in dashboard/lib/pro.ts.\n");
  console.log("PRIVATE (hex, secret):", bytesToHex(priv));
  console.log("PUBLIC  (hex, bundle):", bytesToHex(pub));
}

async function mint() {
  const privHex = process.env.CONDUIT_PRO_PRIVATE_KEY || arg("key", "");
  if (!privHex) {
    console.error("error: provide the signing key via CONDUIT_PRO_PRIVATE_KEY env or --key <hex>");
    console.error("       (run with --genkey to create one first)");
    process.exit(1);
  }
  const priv = hexToBytes(privHex);

  const featuresArg = arg("features", "alerts,analytics,fleet");
  const ALLOWED = ["alerts", "analytics", "fleet"];
  const features = featuresArg.split(",").map((f) => f.trim()).filter(Boolean);
  const bad = features.filter((f) => !ALLOWED.includes(f));
  if (bad.length) {
    console.error(`error: unknown feature(s): ${bad.join(", ")} (allowed: ${ALLOWED.join(", ")})`);
    process.exit(1);
  }

  const expiresArg = arg("expires", "");
  let expires = null;
  if (expiresArg) {
    const d = new Date(expiresArg);
    if (isNaN(d.getTime())) {
      console.error(`error: --expires "${expiresArg}" is not a valid date`);
      process.exit(1);
    }
    expires = d.toISOString();
  }

  // `issued` would normally be new Date(); pass --issued for reproducible output.
  const issuedArg = arg("issued", "");
  const issued = issuedArg ? new Date(issuedArg).toISOString() : new Date().toISOString();

  const payload = {
    plan: arg("plan", "pro"),
    licensee: arg("licensee", "Unnamed"),
    features,
    issued,
    expires,
    id: arg("id", "lic_" + b64url(ed.utils.randomSecretKey()).slice(0, 10)),
  };

  // Sign the EXACT payload bytes that the verifier re-derives from base64url.
  const payloadStr = JSON.stringify(payload);
  const payloadBytes = new TextEncoder().encode(payloadStr);
  const sig = await ed.signAsync(payloadBytes, priv);
  const token = `${b64url(payloadBytes)}.${b64url(sig)}`;

  console.error("# minted license payload:");
  console.error(JSON.stringify(payload, null, 2));
  console.error("# license token (paste into the dashboard's Pro upgrade panel):\n");
  console.log(token);
}

if (has("genkey")) {
  await genkey();
} else {
  await mint();
}
