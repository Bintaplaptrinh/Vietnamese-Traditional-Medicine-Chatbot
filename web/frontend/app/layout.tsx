import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Bloop — Knowledge workspace',
  description: 'Khám phá tri thức y học cổ truyền và kiểm tra nguồn của từng câu trả lời.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="vi" data-theme="light"><body>{children}</body></html>;
}
