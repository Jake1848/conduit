import { Webhook } from "lucide-react";
import { Placeholder } from "@/components/Placeholder";

export default function WebhooksPage() {
  return (
    <Placeholder
      icon={Webhook}
      title="Webhooks"
      description="Event subscriptions — register HTTPS endpoints to receive signed payment.settled / payment.failed events as agents transact."
    />
  );
}
