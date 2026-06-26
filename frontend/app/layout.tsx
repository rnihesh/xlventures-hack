import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppSidebar } from "@/components/app-sidebar";
import { Toaster } from "@/components/ui/toast";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

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
      className={`dark ${inter.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <div className="flex min-h-screen">
          <AppSidebar />
          <div className="flex min-h-screen flex-1 flex-col md:pl-64">
            <main className="flex-1">{children}</main>
          </div>
        </div>
        <Toaster />
      </body>
    </html>
  );
}
