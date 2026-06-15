/**
 * Agent Directory — DATA-LAYER SCAFFOLD ONLY (not wired to any backend yet).
 *
 * This is the *design surface* for a future, opt-in, NON-CUSTODIAL discovery
 * directory: a place an operator could voluntarily LIST an agent's public
 * identity, capabilities, and a payable endpoint so other agents/operators can
 * find and pay it. It is purely coordination/discovery DATA.
 *
 * ⚠️ HARD BOUNDARY — this directory must NEVER:
 *   • hold, custody, or escrow any funds,
 *   • hold private keys or signing material,
 *   • route or proxy payments through any central node.
 * It stores only what a payer needs to *find* a destination and pay it directly,
 * peer-to-peer, over Lightning. The directory is a phone book, not a bank.
 *
 * A listing is opt-in (the operator publishes it), self-attested, and revocable.
 * Trust/reputation, if added later, is metadata over public payment outcomes —
 * never a custodial guarantee.
 */

/** A payable endpoint — the public address a payer sends to. No keys, no funds. */
export interface DirectoryEndpoint {
  /** "lightning_address" (name@host) or "node_pubkey" (66-hex, keysend). */
  kind: "lightning_address" | "node_pubkey";
  value: string;
  /** Optional minimum/suggested price in sats for the advertised service. */
  price_sats?: number;
}

/** One opt-in public listing. Self-attested, revocable, non-custodial. */
export interface AgentDirectoryEntry {
  /** Directory-assigned id, e.g. "dir_…". */
  id: string;
  /** Human label (NOT a Conduit agent_id — that stays private to its operator). */
  display_name: string;
  /** Free-text capability tags, e.g. ["news.fetch", "image.gen"]. */
  capabilities: string[];
  description?: string;
  /** Where to pay it. Direct, peer-to-peer; the directory is never in the path. */
  endpoints: DirectoryEndpoint[];
  /** Optional homepage/docs for the service. */
  url?: string;
  /** Operator-published, self-attested. */
  published_by?: string;
  published_at: string;
  /** Opt-out: an operator can unlist at any time. */
  active: boolean;
}

/**
 * Proposed (UNBUILT) API shape — documented here so the boundary is explicit.
 * None of these would ever move money:
 *   GET    /v1/directory                 — search/list public entries (capabilities, text)
 *   GET    /v1/directory/{id}            — one entry
 *   POST   /v1/directory                 — publish an opt-in listing (operator-authed)
 *   DELETE /v1/directory/{id}            — unlist (operator-authed)
 *
 * Monetization seam (future, opt-in, non-custodial): a subscription or per-lookup
 * fee for *access to the directory service I run* — billed for the service, never a
 * cut of anyone's payment, and never custodial. See docs/ROADMAP.md.
 */
export const DIRECTORY_SCAFFOLD_ONLY = true;
