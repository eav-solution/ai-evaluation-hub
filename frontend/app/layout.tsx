import type {Metadata} from "next";
import type {ReactNode} from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Evaluation Hub",
  description: "Evaluate LLM, RAG, and agent quality in one place.",
};

export default function RootLayout({children}: {children: ReactNode}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400..700;1,400..700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
