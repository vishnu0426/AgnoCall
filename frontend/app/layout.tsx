import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono, Inter } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/AppShell";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
});
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "AgnoCall — AI Call Analysis",
  description: "Enterprise AI conversation intelligence for recorded support calls.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable} ${inter.variable}`}>
      <body className="font-body antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
