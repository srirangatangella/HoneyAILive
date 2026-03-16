import type { Metadata } from "next";
import { DM_Sans } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "HoneyAI Live",
  description: "Real-time multimodal AI guidance for DIY and troubleshooting tasks.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${dmSans.variable} font-sans antialiased`}>{children}</body>
    </html>
  );
}
