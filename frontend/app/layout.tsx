import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "QUANT · Sports Analytics Terminal",
  description: "Quantitative sports analytics platform — +EV signal detection and Kelly sizing",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full scanlines">{children}</body>
    </html>
  );
}
