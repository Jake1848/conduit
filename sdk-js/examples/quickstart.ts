// npm i @conduit/sdk
// CONDUIT_API_KEY=ck_test_... node --experimental-strip-types quickstart.ts

import { Agent } from "@conduit/sdk";

const agent = await Agent.create({
  name: "compute-router-7",
  dailyLimit: 50_000,
});

await agent.policy.attach({
  maxPerHour: 10_000,
  allowlist: ["02beef" + "00".repeat(31)],
});

const receipt = await agent.pay({
  to: "compute-node-7@lnd.conduit.energy",
  sats: 150,
  memo: "dataset query",
});

console.log(receipt.hash, receipt.settledInMs);
