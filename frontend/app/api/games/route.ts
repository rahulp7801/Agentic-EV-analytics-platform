import { NextResponse } from 'next/server';

const ESPN_SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard';

// NBA schedule dates are in Eastern Time — always compute relative to ET
// so a 9pm ET game shows as "Today" even when the server clock is past midnight UTC.
function etDateStr(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  // toLocaleDateString('en-CA') → 'YYYY-MM-DD'
  return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' }).replace(/-/g, '');
}

export async function GET() {
  const dates = [etDateStr(-1), etDateStr(0), etDateStr(1)];
  const labels = ['Yesterday', 'Today', 'Tomorrow'];

  const games: {
    home_abbr: string;
    away_abbr: string;
    home_name: string;
    away_name: string;
    date: string;
    label: string;
    game_time: string;
  }[] = [];

  for (let i = 0; i < dates.length; i++) {
    const dateStr = dates[i];
    try {
      const res = await fetch(`${ESPN_SCOREBOARD}?dates=${dateStr}`, {
        headers: { 'User-Agent': 'QuantSports/1.0' },
      });
      if (!res.ok) continue;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await res.json();
      for (const event of (data.events || [])) {
        const comp = (event.competitions || [{}])[0];
        const competitors = comp.competitors || [];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const home = competitors.find((c: any) => c.homeAway === 'home');
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const away = competitors.find((c: any) => c.homeAway === 'away');
        games.push({
          home_abbr: home?.team?.abbreviation || '',
          away_abbr: away?.team?.abbreviation || '',
          home_name: home?.team?.displayName || '',
          away_name: away?.team?.displayName || '',
          date: dateStr,
          label: labels[i],
          game_time: event.date || '',
        });
      }
    } catch {
      // ESPN unreachable — skip
    }
  }

  return NextResponse.json({ games }, { headers: { 'Cache-Control': 'no-store' } });
}
