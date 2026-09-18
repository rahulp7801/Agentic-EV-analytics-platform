/** Fixed public retrospective holdout records; never live offers or accepted picks. */
export const WEEK_ONE_DEMO=[
  {player:'Matthew Stafford',team:'LAR',opponent:'SF',athlete:'12483',event:'401872657',date:'2026-09-10',
    threshold:200.5,probability:.720588,sample:33,actual:155,
    source_sha256:'1cefdae759629bef7ec6345d4f9e87edcdee907a934f0c04503297c414ebff13'},
  {player:'Brock Purdy',team:'SF',opponent:'LAR',athlete:'4361741',event:'401872657',date:'2026-09-10',
    threshold:200.5,probability:.7,sample:24,actual:205,
    source_sha256:'1cefdae759629bef7ec6345d4f9e87edcdee907a934f0c04503297c414ebff13'},
  {player:'Aaron Rodgers',team:'PIT',opponent:'ATL',athlete:'8439',event:'401872658',date:'2026-09-13',
    threshold:200.5,probability:.632353,sample:33,actual:221,
    source_sha256:'d9809ccb7867c49f53a53ddd00b9249eba6cc9e21cb4af1ec8fcd1cc29b95a4d'},
] as const;
export const DEFAULT_DEMO_INDEX=1;
export function demoResult(record:typeof WEEK_ONE_DEMO[number]) {
  return {outcome:record.actual>record.threshold ? 'Above threshold' : 'Below threshold',
    correct:(record.probability>.5)===(record.actual>record.threshold),
    recommendation:'Research only',historical_price:null,profit:null,execution_ready:false};
}
