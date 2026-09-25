export function RewardIndicator({ active = false }: { active?: boolean }) {
  return <span className={`reward-indicator${active ? ' is-processing' : ''}`} aria-hidden="true">XLM</span>
}
