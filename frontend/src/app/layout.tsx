import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/auth/AuthContext";

export const metadata: Metadata = { title: "DataPilot AI", description: "Ask questions of your spreadsheet data" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" suppressHydrationWarning><body suppressHydrationWarning><AuthProvider>{children}</AuthProvider></body></html>;
}
