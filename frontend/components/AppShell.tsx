"use client";

import { usePathname } from "next/navigation";
import Sidebar from "@/components/Sidebar";

/**
 * The app frame (sidebar + content). The sign-in page is a stand-alone screen: someone who has not signed
 * in yet must not be shown the app's navigation, so it renders without the frame.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/login" || pathname.startsWith("/login/")) return <>{children}</>;
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}
