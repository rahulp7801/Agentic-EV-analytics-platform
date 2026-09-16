import { connection } from 'next/server';
import LandingPage from '@/components/LandingPage';

export default async function Home() {
  await connection();
  return <LandingPage />;
}
