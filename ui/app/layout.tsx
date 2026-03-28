import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import { QueryProvider } from "@/providers/query-provider";
import "./globals.css";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Tensory — Context-Aware Memory for AI Agents",
    template: "%s | Tensory",
  },
  description:
    "Episodic, semantic & procedural memory with built-in collision detection. One-file cognitive stack for any AI agent.",
  metadataBase: new URL("https://tensory.dev"),
  openGraph: {
    title: "Tensory — Context-Aware Memory for AI Agents",
    description:
      "Full cognitive stack: episodic + semantic + procedural memory, graph relations, hybrid search with MMR diversity.",
    siteName: "Tensory",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Tensory — Context-Aware Memory for AI Agents",
    description:
      "Full cognitive stack: episodic + semantic + procedural memory, graph relations, hybrid search with MMR diversity.",
  },
  keywords: [
    "AI memory",
    "agent memory",
    "episodic memory",
    "semantic memory",
    "procedural memory",
    "knowledge graph",
    "RAG",
    "cognitive architecture",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
