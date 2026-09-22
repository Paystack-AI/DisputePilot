import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Frontend',
  description: 'Web app team placeholder',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
