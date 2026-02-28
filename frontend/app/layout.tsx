import './globals.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'worldview-local',
  description: 'Local-only situational awareness dashboard'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
