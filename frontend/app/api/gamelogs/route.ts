import { database, hosted } from '@/lib/database';
import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { ROOT, PYTHON } from '@/lib/python';




// Python script reads sport/player/limit from environment variables, never from
// command-line args or stdin interpolation — eliminates shell injection risk.
const SCRIPT = `
import sys, json, os
sys.path.insert(0,'src'); sys.path.insert(0,'site-packages')
from dotenv import load_dotenv; load_dotenv(dotenv_path='.env')
from sportsbet.config import settings
import psycopg

sport  = os.environ.get('GAMELOGS_SPORT', 'nba')
player = os.environ.get('GAMELOGS_PLAYER', '')
limit  = int(os.environ.get('GAMELOGS_LIMIT', '30'))

url = str(settings.database_url).replace('postgresql+psycopg://','postgresql://')
with psycopg.connect(url, connect_timeout=15) as conn:
    if sport == "nba":
        # Column names match NBAPlayerGameLog ORM (db/models.py).
        # wl (win/loss) is not stored in nba_player_gamelogs — omitted.
        rows = conn.execute(
            "SELECT game_date::text, player_name, team_abbreviation, opponent_team, "
            "is_home, points, rebounds, assists, threes_made, steals, blocks, minutes "
            "FROM nba_player_gamelogs "
            "WHERE 1=1 "
            + ("AND LOWER(player_name) LIKE LOWER(%s) " if player else "")
            + "ORDER BY game_date DESC LIMIT %s",
            ('%' + player + '%', limit) if player else (limit,)
        ).fetchall()
        cols = ['date','player','team','opponent','is_home','points','rebounds','assists','threes','steals','blocks','minutes']
    else:
        rows = []
        cols = []
    print(json.dumps({"logs": [dict(zip(cols, r)) for r in rows]}))
`;

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const player = searchParams.get('player') || '';
  const sport  = searchParams.get('sport')  || 'nba';
  const limit  = parseInt(searchParams.get('limit') || '30', 10);

  // Validate inputs before passing to subprocess
  const validSport = sport === 'nba' || sport === 'nfl' ? sport : 'nba';
  const safeLimit  = isNaN(limit) || limit < 1 ? 30 : Math.min(limit, 200);

  if (hosted) {
    try {
      if (validSport !== 'nba') return NextResponse.json({logs:[], error:'NFL game logs are not available in this view yet.'});
      const {rows} = await database().query(
        "SELECT game_date::text AS date, player_name AS player, team_abbreviation AS team, opponent_team AS opponent, is_home, points, rebounds, assists, threes_made AS threes, steals, blocks, minutes FROM nba_player_gamelogs WHERE ($1 = '' OR player_name ILIKE $2) ORDER BY game_date DESC LIMIT $3",
        [player, `%${player}%`, safeLimit]);
      return NextResponse.json({logs:rows});
    } catch { return NextResponse.json({error:'Game logs are temporarily unavailable.',logs:[]},{status:503}); }
  }
  try {
    const {stdout} = await promisify(execFile)(PYTHON, ['-c', SCRIPT], {
      cwd: ROOT, timeout: 20000, encoding: 'utf-8',
      env: {...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1',
        GAMELOGS_SPORT: validSport, GAMELOGS_PLAYER: player, GAMELOGS_LIMIT: String(safeLimit)},
    });
    return NextResponse.json(JSON.parse(stdout.trim()));
  } catch {
    return NextResponse.json({error: 'Game logs unavailable. Check database configuration.', logs: []}, {status: 503});
  }
}
