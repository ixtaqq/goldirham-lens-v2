import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import { Barlow_Condensed } from "next/font/google";
import type { ReactNode } from "react";

import { BOOT_SCRIPT, MOTION_ENABLED } from "@/lib/motion-pref";

import "./globals.css";

const display = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-barlow",
  display: "swap",
});

const DESCRIPTION =
  "A private research service that sends one Telegram briefing a day. Python computes and checks every figure. This showcase runs the real pipeline on synthetic demo data.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://goldirham-lens.vercel.app"),
  title: "Goldirham Lens · Numbers before narrative",
  description: DESCRIPTION,
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    title: "Goldirham Lens · Numbers before narrative",
    description: DESCRIPTION,
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "Numbers before narrative. Demo data, synthetic market." }],
  },
  twitter: { card: "summary_large_image", images: ["/og.png"] },
};

export const viewport: Viewport = {
  themeColor: "#07110e",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en-MY"
      className={`${display.variable} ${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {MOTION_ENABLED ? <script dangerouslySetInnerHTML={{ __html: BOOT_SCRIPT }} /> : null}
      </head>
      <body>{children}</body>
    </html>
  );
}
