import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "Audio Collection Analyzer",
  description: "Analyze audio websites by year, discover albums and songs, and download authorized collections as organized ZIP archives.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-100 text-gray-900 antialiased">
        <NavBar />
        {children}
      </body>
    </html>
  );
}
