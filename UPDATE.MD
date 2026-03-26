Update the Quant-Sports Agentic Platform to support Situational Game-Log Prop Queries for both NBA and NFL player props.

Currently, the system uses simple historical frequencies (NFL play-by-play) or season aggregates (NBA `LeagueDashPlayerStats` season totals) to calculate standard "True Probability." This completely ignores situational context. I need the `QuantAgent` and [PropQueryBuilder](cci:2://file:///c:/Users/rahul/ucla/pp/sportsbet/src/sportsbet/prop/query_builder.py:78:0-135:31) to dynamically analyze player performance in highly specific, conditional game states.

For example, the system must be able to evaluate: "What is Stephen Curry's true probability of scoring Over 25.5 points specifically when Draymond Green is Out AND they are playing Away over the last 10 games?"

Please implement the following architectural changes:

1. **Ingestion & Database Schema Updates**:
   - The current `nba_player_stats` table only stores season totals. Create a new `nba_player_gamelogs` table and an ingest pipeline to pull individual game logs (Date, Opponent, Home/Away, Minutes, Points, Rebounds, Assists, etc.).
   - Ensure both NFL and NBA schemas can join a player's performance against the inactive/injury list for that specific game_id to determine if a key teammate or opponent was missing.

2. **GraphState and PropParams Extension**:
   - Extend the `PropParams` Pydantic model in [src/sportsbet/graph/models.py](cci:7://file:///c:/Users/rahul/ucla/pp/sportsbet/src/sportsbet/graph/models.py:0:0-0:0). It must accept optional situational filters such as:
     - `last_n_games` (int)
     - `teammate_out` (list of player IDs)
     - `opponent_team` (str)
     - `home_away` (Literal["home", "away"])
   - Update `GraphState` so the `ContextAgent` can inject these situational parameters into the state after reading the live news (e.g., if the ContextAgent sees Jimmy Butler is ruled out, it populates `teammate_out` for Bam Adebayo's prop queries).

3. **QueryBuilder Modifications**:
   - Update [src/sportsbet/prop/nba_query_builder.py](cci:7://file:///c:/Users/rahul/ucla/pp/sportsbet/src/sportsbet/prop/nba_query_builder.py:0:0-0:0) and [src/sportsbet/prop/query_builder.py](cci:7://file:///c:/Users/rahul/ucla/pp/sportsbet/src/sportsbet/prop/query_builder.py:0:0-0:0).
   - Instead of querying season aggregates, the SQL templates must dynamically construct `WHERE` clauses based on the new `PropParams` situational filters (e.g., filtering `nba_player_gamelogs` by `opponent`, sorting by `game_date DESC LIMIT $N` for recent form).
   - Remember the rigid security model: DO NOT use f-string SQL interpolation for user data. Add these new filters cleanly to `PROP_ALLOWED_FILTER_KEYS` and pass them as positional `asyncpg` `$N` parameters.

4. **Quant Executor Adjustments**:
   - In `prop/executor.py` and `prop/nba_executor.py`, adjust the sample size logic. If estimating Stephen Curry's points when Draymond Green sits, the sample size will be much smaller than the standard 30-game `MIN_SAMPLE_SIZE`.
   - Ensure the Wilson Confidence Interval (`proportion_confint`) gracefully handles these smaller, highly specific conditional samples and widens the confidence band accordingly before returning the `PropResult`.

Walk through your plan before modifying the files, particularly focusing on the SQL query templates necessary to join individual game logs with historical injury/inactive statuses.
