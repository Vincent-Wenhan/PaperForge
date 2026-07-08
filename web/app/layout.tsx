import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PaperForge",
  description: "Turn research papers into runnable Next.js apps",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
