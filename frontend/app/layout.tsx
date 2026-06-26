import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
