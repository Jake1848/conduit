import { FileText } from "lucide-react";
import { Placeholder } from "@/components/Placeholder";

export default function DocsPage() {
  return (
    <Placeholder
      icon={FileText}
      title="Docs"
      description="Developer documentation — API reference, SDK guides, and integration walkthroughs for building agents on Conduit."
    />
  );
}
