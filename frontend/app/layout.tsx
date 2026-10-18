import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/lib/query/query-provider";

export const metadata: Metadata = {
  title: "Overseas Ads Agent",
  description: "Meta-first advertising operations SaaS with draft-first agent approvals.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
