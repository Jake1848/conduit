export { Agent } from "./agent.js";
export type {
  Receipt,
  Invoice,
  Transaction,
  SendOptions,
  LedgerAdjustment,
} from "./agent.js";
export { ConduitClient } from "./conduit-client.js";
export type { SendPaymentOptions, FundOptions } from "./conduit-client.js";
export { Policy } from "./policy.js";
export { Conduit, defaultClient, setDefaultClient } from "./client.js";
export type { ConduitOptions, RequestOptions } from "./client.js";
export { verifyWebhook, parseWebhook, WebhookVerificationError } from "./webhook.js";
export {
  ConduitError,
  AuthenticationError,
  PermissionDenied,
  AgentNotFound,
  PolicyViolation,
  InsufficientBalance,
  PaymentFailed,
  RateLimited,
} from "./errors.js";
export type {
  AgentJSON,
  ReceiptJSON,
  InvoiceJSON,
  TransactionJSON,
  Balance,
  PayOptions,
  CreateAgentOptions,
  PolicyAttachOptions,
  Scope,
  TxStatus,
  Direction,
} from "./types.js";

// L402 engine
export {
  L402Engine,
  MemoryTokenStore,
  parseChallenge,
  agentPayer,
  // Typed errors
  L402Error,
  InvalidChallenge,
  UnsupportedChallenge,
  PaymentRejected,
  RepayCapExceeded,
  PreimageError,
} from "./l402.js";
export type {
  L402Config,
  PaidResult,
  ParsedChallenge,
  CachedToken,
  FetchResult,
  FetcherFn,
  ITokenStore,
  PayInvoiceFn,
  AgentLike,
} from "./l402.js";

// L402 fetch wrapper
export { fetchWithL402, createAgentFetch } from "./l402-fetch.js";
export type { FetchWithL402Options } from "./l402-fetch.js";
