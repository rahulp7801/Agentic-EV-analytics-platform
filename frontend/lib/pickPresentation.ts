export type PickDisplayState='live'|'recorded'|'locked';

type BoardLike={board_state?:unknown};

export function pickDisplayState(value:BoardLike):PickDisplayState {
  return value.board_state==='recorded' || value.board_state==='locked' ? value.board_state : 'live';
}

export function pickCardPresentation(value:BoardLike,rank:number) {
  const state=pickDisplayState(value),safeRank=Number.isSafeInteger(rank) && rank>0 ? rank : 1;
  if(state==='live') return {
    state,actionable:true,rankLabel:safeRank===1 ? 'Top qualified pick' : `Qualified pick #${safeRank}`,
    status:'Live price',priceLabel:'Current price',returnLabel:'Expected net per $100',
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
    state:'live' as const,eyebrow:'Qualified now',title:'Picks you can check now',
    description:'One primary line per player, ranked by the conservative probability edge.',
    count:`${liveCount} live`,
  };
  if(retainedCount>0) return {
    state:'recorded' as const,eyebrow:'Recorded board',title:'Last approved picks',
    description:'These exact captures passed every gate earlier. Prices shown are historical.',
    count:`0 live · ${retainedCount} to reprice`,
  };
  return {
    state:'empty' as const,eyebrow:'Qualified now',title:'No approved pick yet',
    description:'The board stays empty until a line clears every evidence and price gate.',count:'0 live',
  };
}
