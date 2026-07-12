import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider } from "@/lib/toast";

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
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          // ponytail: Apply theme before paint to avoid flash.
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('paperforge-theme');var d=t==='dark';if(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches)d=true;document.documentElement.classList.toggle('dark',d);}catch(e){}})();`,
          }}
        />
      </head>
      <body>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
