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

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
const SITE_DESCRIPTION =
  "An agentic platform for explainable, evidence-backed next best actions across your accounts.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Aperture | Explainable Next Best Action",
    template: "%s | Aperture",
  },
  description: SITE_DESCRIPTION,
  applicationName: "Aperture",
  // app/icon.png and app/apple-icon.png are auto-detected; declared here too so
  // crawlers and the browser tab pick up the mark explicitly.
  icons: {
    icon: "/icon.png",
    apple: "/apple-icon.png",
  },
  openGraph: {
    type: "website",
    siteName: "Aperture",
    title: "Aperture | Explainable Next Best Action",
    description: SITE_DESCRIPTION,
    url: SITE_URL,
  },
  twitter: {
    card: "summary_large_image",
    title: "Aperture | Explainable Next Best Action",
    description: SITE_DESCRIPTION,
  },
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
