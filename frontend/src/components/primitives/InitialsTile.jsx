import clsx from 'clsx'
import { initials, pastelFor } from '../../lib/format'

const BG = {
  pink: 'bg-pastel-pink text-pastel-pink-ink',
  purple: 'bg-pastel-purple text-pastel-purple-ink',
  yellow: 'bg-pastel-yellow text-pastel-yellow-ink',
  blue: 'bg-pastel-blue text-pastel-blue-ink',
}

const SIZE = {
  sm: 'h-8 w-8 text-[10px] rounded-lg',
  md: 'h-10 w-10 text-xs rounded-xl',
  lg: 'h-12 w-12 text-sm rounded-xl',
}

// Locally-generated placeholder "image" for products/avatars — a solid
// pastel tile with initials. Never hotlinks anything.
export default function InitialsTile({ name, size = 'md', className }) {
  const tone = BG[pastelFor(name)]
  return (
    <div
      aria-hidden="true"
      className={clsx(
        'flex shrink-0 items-center justify-center font-semibold',
        SIZE[size],
        tone,
        className,
      )}
    >
      {initials(name)}
    </div>
  )
}
