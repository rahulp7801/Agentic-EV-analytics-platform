export type PickDisplayState='live'|'recorded'|'locked';

type BoardLike={board_state?:unknown};

export function pickDisplayState(value:BoardLike):PickDisplayState {
  return value.board_state==='recorded' || value.board_state==='locked' ? value.board_state : 'live';
}

export function pickCardPresentation(value:BoardLike,rank:number) {
  const state=pickDisplayState(value),safeRank=Number.isSafeInteger(rank) && rank>0 ? rank : 1;
  if(state==='live') return {
    state,actionable:true,rankLabel:safeRank===1 ? 'Top suggested pick' : `Suggested pick #${safeRank}`,
    status:'Live price',priceLabel:'Current price',returnLabel:'Model-estimated net per $100',
  } as const;
  if(state==='locked') return {
    state,actionable:false,rankLabel:safeRank===1 ? 'Top locked pick' : `Locked pick #${safeRank}`,
    status:'Locked T−60',priceLabel:'Locked price',returnLabel:'At locked price',
  } as const;
  return {
    state,actionable:false,rankLabel:safeRank===1 ? 'Top recorded pick' : `Recorded pick #${safeRank}`,
    status:'Price expired',priceLabel:'Recorded price',returnLabel:'At recorded price',
  } as const;
}

export function shortlistPresentation(liveCount:number,retainedCount:number) {
  if(liveCount>0) return {
    state:'live' as const,eyebrow:'Suggested picks',title:'Suggested picks you can check now',
    description:'Player-history estimates screened against the captured price, roster, injury reports and risk limits. One line per player.',
    count:`${liveCount} live`,
  };
  if(retainedCount>0) return {
    state:'recorded' as const,eyebrow:'Recorded board',title:'Last approved picks',
    description:'These exact captures passed every gate earlier. Prices shown are historical.',
    count:`0 live · ${retainedCount} to reprice`,
  };
  return {
    state:'empty' as const,eyebrow:'Suggested picks',title:'No current suggested pick available',
    description:'Collection status and evidence checks determine when a current pick can be shown.',count:'0 live',
  };
}
