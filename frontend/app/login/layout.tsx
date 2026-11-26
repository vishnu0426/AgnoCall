import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign in · AgnoCall",
  description: "Sign in to AgnoCall.",
  robots: { index: false, follow: false },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
