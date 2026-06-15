"use client";

import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/lib/toast";
import { ProProvider } from "@/lib/pro";
import { AppShell } from "./AppShell";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <ToastProvider>
        {/* Pro = OPTIONAL dashboard-only convenience gating. It never touches the
            core payment path; the app works fully without any license. */}
        <ProProvider>
          <AppShell>{children}</AppShell>
        </ProProvider>
      </ToastProvider>
    </AuthProvider>
  );
}
