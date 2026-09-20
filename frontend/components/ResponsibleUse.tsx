import styles from './ResponsibleUse.module.css';

export default function ResponsibleUse({compact=false}:{compact?:boolean}) {
  return <aside className={compact ? styles.compact : styles.notice} aria-label="Responsible use notice">
    <strong>Research only.</strong> Not financial, gambling, or legal advice. Sports markets involve risk.
    You are solely responsible for verifying every price, eligibility rule, local law, and decision.
    Linework does not place bets or guarantee outcomes.
  </aside>;
}
