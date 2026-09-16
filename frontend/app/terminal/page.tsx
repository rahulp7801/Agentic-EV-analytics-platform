import { connection } from 'next/server';
import TerminalApp from '@/components/TerminalApp';

export default async function TerminalPage() {
  await connection();
  return <TerminalApp />;
}
