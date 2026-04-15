import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";
import { Nav } from "@/components/nav";
import { Footer } from "@/components/footer";
import { AuthProvider } from "@/components/auth-provider";
import { ErrorBoundary } from "@/components/error-boundary";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Minis — Clone any developer's mind",
  description:
    "Enter a GitHub username. We'll mine their commits, PRs, and reviews to create an AI that thinks like them.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} font-sans antialiased`}
      >
        <AuthProvider>
          <ErrorBoundary>
            <Nav />
            <main className="min-h-[calc(100vh-3.5rem)]">{children}</main>
            <Footer />
          </ErrorBoundary>
          <Toaster richColors theme="dark" position="bottom-right" />
        </AuthProvider>
      </body>
    </html>
  );
}
