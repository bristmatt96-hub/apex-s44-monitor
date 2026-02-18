import type { Metadata, Viewport } from 'next'
import '@/styles/globals.css'
import { NavBar } from '@/components/layout/nav-bar'

export const metadata: Metadata = {
  title: 'APEX Dashboard',
  description: 'Trading system dashboard',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'APEX',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: '#0a0a0a',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-background text-foreground min-h-screen pb-20">
        <main className="max-w-lg mx-auto px-4 py-6">
          {children}
        </main>
        <NavBar />
      </body>
    </html>
  )
}
