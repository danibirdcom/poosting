import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Redactia",
  description: "Plataforma editorial automatizada",
};

/*
 * Root layout mínimo: solo `<html>` + `<body>`. La chrome (sidebar +
 * header) vive en `(app)/layout.tsx` para que /login no la herede.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
