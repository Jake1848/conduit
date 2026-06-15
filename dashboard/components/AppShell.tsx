"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { AppDataProvider } from "@/lib/appdata";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { LoginScreen } from "./LoginScreen";

export function AppShell({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const pathname = usePathname();
  const contentRef = useRef<HTMLDivElement>(null);

  // Reset content scroll on navigation (matches the prototype).
  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [pathname]);

  // Public routes render standalone — no login, no operator shell. The /stats
  // transparency page is intentionally public (it shows only opt-in aggregates).
  const PUBLIC_ROUTES = ["/stats"];
  if (PUBLIC_ROUTES.some((r) => pathname === r || pathname.startsWith(r + "/"))) {
    return <>{children}</>;
  }

  if (status === "loading") {
    return (
      <div className="login-wrap">
        <span className="spinner" style={{ width: 26, height: 26 }} />
      </div>
    );
  }

  if (status === "unauthed") {
    return <LoginScreen />;
  }

  return (
    <AppDataProvider>
      <div className="app">
        <Sidebar />
        <div className="main">
          <Topbar />
          <div className="content" ref={contentRef}>
            <div className="content-inner">{children}</div>
          </div>
        </div>
      </div>
    </AppDataProvider>
  );
}
