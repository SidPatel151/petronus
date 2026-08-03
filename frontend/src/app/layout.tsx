import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Petronus — Automated Building Design for California',
  description: 'Generate coordinated architectural and MEP concept models for California residential projects',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
