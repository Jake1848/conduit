export class ConduitError extends Error {
  code: string;
  detail: Record<string, unknown>;
  constructor(message: string, code = "CONDUIT_ERROR", detail: Record<string, unknown> = {}) {
    super(message);
    this.name = "ConduitError";
    this.code = code;
    this.detail = detail;
  }
}

export class AuthenticationError extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "AUTHENTICATION_ERROR", d);
    this.name = "AuthenticationError";
  }
}
export class PermissionDenied extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "PERMISSION_DENIED", d);
    this.name = "PermissionDenied";
  }
}
export class AgentNotFound extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "AGENT_NOT_FOUND", d);
    this.name = "AgentNotFound";
  }
}
export class PolicyViolation extends ConduitError {
  constructor(m: string, code = "POLICY_VIOLATION", d: Record<string, unknown> = {}) {
    super(m, code, d);
    this.name = "PolicyViolation";
  }
}
export class InsufficientBalance extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "INSUFFICIENT_BALANCE", d);
    this.name = "InsufficientBalance";
  }
}
export class PaymentFailed extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "PAYMENT_FAILED", d);
    this.name = "PaymentFailed";
  }
}
export class RateLimited extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "RATE_LIMITED", d);
    this.name = "RateLimited";
  }
}

const POLICY_CODES = new Set([
  "POLICY_VIOLATION",
  "DAILY_LIMIT_EXCEEDED",
  "HOURLY_LIMIT_EXCEEDED",
  "PER_TRANSACTION_LIMIT_EXCEEDED",
  "RATE_LIMIT_EXCEEDED",
  "DESTINATION_BLOCKLISTED",
  "DESTINATION_NOT_ALLOWLISTED",
  "POLICY_DISABLED",
  "MEMO_REQUIRED",
  "AGENT_INACTIVE",
]);

export function throwForResponse(status: number, body: unknown): never {
  const detail =
    body && typeof body === "object" && "detail" in body
      ? ((body as { detail: unknown }).detail as Record<string, unknown>)
      : ({} as Record<string, unknown>);
  const code = String(detail.code ?? detail.error ?? "CONDUIT_ERROR").toUpperCase();
  const message = String(detail.detail ?? detail.message ?? `HTTP ${status}`);
  const rest = { ...detail };
  delete rest.code;
  delete rest.detail;
  delete rest.error;

  if (POLICY_CODES.has(code)) throw new PolicyViolation(message, code, rest);
  switch (code) {
    case "AUTHENTICATION_ERROR":
      throw new AuthenticationError(message, rest);
    case "PERMISSION_DENIED":
      throw new PermissionDenied(message, rest);
    case "AGENT_NOT_FOUND":
      throw new AgentNotFound(message, rest);
    case "INSUFFICIENT_BALANCE":
      throw new InsufficientBalance(message, rest);
    case "PAYMENT_FAILED":
      throw new PaymentFailed(message, rest);
    case "RATE_LIMITED":
      throw new RateLimited(message, rest);
    default:
      throw new ConduitError(message, code, rest);
  }
}
