"""Parallel market specialists sharing one validated payoff and risk contract."""
from __future__ import annotations

import hashlib
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from sportsbet.arbitrage.portfolio import MarketAnalysisRequest, analyze_candidate, specialist


class MarketState(TypedDict, total=False):
    request: MarketAnalysisRequest
    sportsbook: list[dict]
    kalshi: list[dict]
    prizepicks: list[dict]
    report: dict


def create_market_graph():
    graph = StateGraph(MarketState)

    def validate(state):
        return {'request': MarketAnalysisRequest.model_validate(state['request'])}

    graph.add_node('validate', validate)
    graph.add_edge(START, 'validate')
    for venue in ('sportsbook', 'kalshi', 'prizepicks'):
        def evaluate(state, venue=venue):
            request = state['request']
            results=[]
            for candidate in request.candidates:
                if specialist(candidate)!=venue:continue
                try:
                    result=analyze_candidate(candidate,request)
                except Exception as exc:
                    # One failed solver must not discard other candidates or
                    # expose input documents/account details through exception text.
                    result=dict(candidate_id=candidate.candidate_id,specialist=venue,
                        status='failed',reasons=['analysis_failed'],error_type=type(exc).__name__,
                        units={},cost=None,state_profits={},worst_profit=None,execution_ready=False)
                results.append(result)
            return {venue:results}
        graph.add_node(venue, evaluate)
        graph.add_edge('validate', venue)

    def risk_report(state):
        request = state['request']
        results = sorted(state['sportsbook'] + state['kalshi'] + state['prizepicks'],
                         key=lambda result: result['candidate_id'])
        failed=sum(result['status']=='failed' for result in results)
        return {'report': dict(schema_version=1, as_of=request.as_of.isoformat(),
            input_sha256=hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
            results=results, status='degraded' if failed else 'complete',failed_count=failed,execution_ready=False,
            scope='Independent candidate scenarios, not a funded portfolio, fills, or realized profit. '
                  'Coverage review and fee bounds are caller-supplied evidence, not automatically verified.')}

    graph.add_node('risk_report', risk_report)
    graph.add_edge(['sportsbook', 'kalshi', 'prizepicks'], 'risk_report')
    graph.add_edge('risk_report', END)
    return graph.compile()


def make_market_analysis_node():
    graph = create_market_graph()

    async def market_analysis_node(state):
        result = await graph.ainvoke({'request': state['market_request']})
        return {'market_report': result['report']}

    return market_analysis_node
