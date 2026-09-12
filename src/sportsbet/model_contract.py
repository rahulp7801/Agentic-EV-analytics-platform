"""Shared identity for the model evaluated by scans and published metrics."""

MODEL_VERSION = 'empirical-jeffreys-v4'

PROP_MARKETS = {
    'nba': {'player_points': 'points', 'player_rebounds': 'rebounds',
            'player_assists': 'assists'},
    'nfl': {'player_pass_yds': 'pass_yds', 'player_rush_yds': 'rush_yds',
            'player_reception_yds': 'rec_yds', 'player_receptions': 'receptions'},
}

# These scanner cohorts were introduced after quote source and normalized-row
# commitments became mandatory. Advancing MODEL_VERSION must not make their
# historical records exempt from provenance validation.
QUOTE_PROVENANCE_MODEL_VERSIONS = frozenset({
    'empirical-v2',
    'empirical-jeffreys-v3',
    'empirical-jeffreys-v4',
})
