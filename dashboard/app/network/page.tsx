import { Share2 } from "lucide-react";
import { Placeholder } from "@/components/Placeholder";

export default function NetworkPage() {
  return (
    <Placeholder
      icon={Share2}
      title="Network"
      description="Lightning routing topology — channels, peers, and liquidity across the Conduit node. A live graph of the fleet's settlement paths."
    />
  );
}
