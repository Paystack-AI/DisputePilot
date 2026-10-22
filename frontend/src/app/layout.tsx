import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';
import { themeBootScript } from '@/lib/theme';

const inter = Inter({ subsets: ['latin'], variable: '--font-sans', display: 'swap' });

export const metadata: Metadata = {
  title: {
    default: 'DisputePilot · TrustLayer',
    template: '%s · DisputePilot',
  },
  description:
    'Reconcile daily. Defend disputes instantly. Prove your trust publicly with DisputePilot and TrustLayer.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // the boot script sets the theme class before react hydrates
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
