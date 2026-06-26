import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { AuthProvider } from "@/lib/auth-context";
import { Toaster } from "@/components/ui/toast";

// Set the theme class before first paint so there is no flash. Stored
// preference wins; otherwise we respect the OS setting (default dark brand).
const themeScript = `(function(){try{var s=localStorage.getItem('aperture-theme');var dark=s?s==='dark':(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);var c=document.documentElement.classList;if(dark){c.add('dark');}else{c.remove('dark');}}catch(e){}})();`;

export const metadata: Metadata = {
  title: "Aperture | Explainable Next Best Action",
  description:
    "An agentic platform for explainable, evidence-backed next best actions across your accounts.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`dark ${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
        <Toaster />
      </body>
    </html>
  );
}
