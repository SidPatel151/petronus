import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Petronus — Automated Building Design for California',
  description: 'Generate complete MEP building models for CA multi-family residential',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
