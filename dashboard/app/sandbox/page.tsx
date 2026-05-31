import { Box } from "lucide-react";
import { Placeholder } from "@/components/Placeholder";

export default function SandboxPage() {
  return (
    <Placeholder
      icon={Box}
      title="Sandbox"
      description="A safe test environment for trying payment flows against a regtest-backed fleet before going live on mainnet."
    />
  );
}
