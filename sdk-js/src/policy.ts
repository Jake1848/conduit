import { Conduit, defaultClient } from "./client.js";
import type { Agent } from "./agent.js";
import type { PolicyAttachOptions } from "./types.js";

export class Policy {
  maxPerTransaction: number | null = null;
  maxPerHour: number | null = null;
  maxPerDay: number | null = null;
  maxPerMinuteCount = 60;
  allowlist: string[] = [];
  blocklist: string[] = [];
  requireMemo = false;
  enabled = true;

  constructor(
    private readonly agent: Agent,
    private readonly client: Conduit = defaultClient(),
  ) {}

  async attach(opts: PolicyAttachOptions = {}): Promise<Policy> {
    const data = await this.client.post<Record<string, unknown>>(
      `/v1/agents/${this.agent.id}/policy`,
      {
        max_per_transaction: opts.maxPerTransaction ?? null,
        max_per_hour: opts.maxPerHour ?? null,
        max_per_day: opts.maxPerDay ?? null,
        max_per_minute_count: opts.maxPerMinuteCount ?? 60,
        allowlist: opts.allowlist ?? null,
        blocklist: opts.blocklist ?? null,
        require_memo: opts.requireMemo ?? false,
        enabled: opts.enabled ?? true,
      },
    );
    this.hydrate(data);
    return this;
  }

  async fetch(): Promise<Policy> {
    const data = await this.client.get<Record<string, unknown>>(
      `/v1/agents/${this.agent.id}/policy`,
    );
    this.hydrate(data);
    return this;
  }

  async remove(): Promise<void> {
    await this.client.delete(`/v1/agents/${this.agent.id}/policy`);
  }

  private hydrate(d: Record<string, unknown>): void {
    this.maxPerTransaction = (d.max_per_transaction as number | null) ?? null;
    this.maxPerHour = (d.max_per_hour as number | null) ?? null;
    this.maxPerDay = (d.max_per_day as number | null) ?? null;
    this.maxPerMinuteCount = (d.max_per_minute_count as number) ?? 60;
    this.allowlist = (d.allowlist as string[]) ?? [];
    this.blocklist = (d.blocklist as string[]) ?? [];
    this.requireMemo = Boolean(d.require_memo);
    this.enabled = d.enabled !== false;
  }
}
