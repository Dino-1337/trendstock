import clsx from 'clsx'

// Same fixed dimensions as the real card it stands in for, so nothing
// shifts on the page once real data arrives.
export function SkeletonBlock({ className }) {
  return <div className={clsx('animate-pulse rounded-chip bg-black/5', className)} />
}

export function SkeletonStatCard() {
  return (
    <div className="flex h-[132px] flex-col justify-between rounded-card border border-hairline bg-card card-shadow p-5">
      <div className="flex items-center gap-3">
        <SkeletonBlock className="h-9 w-9 rounded-full" />
        <SkeletonBlock className="h-3 w-20" />
      </div>
      <div className="flex items-end justify-between">
        <SkeletonBlock className="h-7 w-16" />
        <SkeletonBlock className="h-6 w-14 rounded-full" />
      </div>
    </div>
  )
}

export default function SkeletonCard({ className }) {
  return (
    <div
      className={clsx(
        'flex flex-col gap-3 rounded-card border border-hairline bg-card card-shadow p-5 md:p-6',
        className,
      )}
    >
      <SkeletonBlock className="h-5 w-1/3" />
      <SkeletonBlock className="flex-1" />
    </div>
  )
}
