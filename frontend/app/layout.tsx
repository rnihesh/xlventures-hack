import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppSidebar } from "@/components/app-sidebar";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

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
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <div className="flex min-h-screen">
          <AppSidebar />
          <div className="flex min-h-screen flex-1 flex-col md:pl-64">
            <main className="flex-1">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
