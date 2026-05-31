import { ShieldCheck } from "lucide-react";
import { Placeholder } from "@/components/Placeholder";

export default function PoliciesPage() {
  return (
    <Placeholder
      icon={ShieldCheck}
      title="Policies"
      description="Reusable spending rule sets — max per tx/hour/day, allowlists and blocklists — that can be attached to any agent. Per-agent policy editing lives on each agent's detail page today."
    />
  );
}
