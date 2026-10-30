import type { Metadata } from "next";
import "./globals.css";

// System font stack instead of next/font/google, so `next build` works fully
// OFFLINE (no fetch to fonts.googleapis.com). The CSS variables are kept so any
// `var(--font-geist-*)` references in the styles still resolve.
const fontVars = {
  "--font-geist-sans": "system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
  "--font-geist-mono": "ui-monospace, 'Cascadia Code', Consolas, 'Courier New', monospace",
} as React.CSSProperties;

export const metadata: Metadata = {
  title: "NTPC AI Assistant",
  description: "NTPC internal knowledge assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" style={fontVars}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
