import { useState } from 'react'
import clsx from 'clsx'
import InitialsTile from './InitialsTile'

const SIZE_PX = {
  sm: 'h-8 w-8 rounded-lg',
  md: 'h-10 w-10 rounded-xl',
  lg: 'h-12 w-12 rounded-xl',
}

// Remote product thumbnail with a graceful local fallback. `image_src` values
// come straight from the uploaded CSV's "Image Src" column (Shopify CDN, or
// picsum.photos in the bundled fixture) — a real remote URL, not a local
// asset. An offline machine or a dead link must never surface a browser's
// broken-image icon, so any load failure (or a missing src to begin with)
// swaps to the same InitialsTile placeholder used everywhere else a product
// has no art.
export default function ProductThumb({ src, name, size = 'md', className }) {
  const [failed, setFailed] = useState(false)

  if (!src || failed) {
    return <InitialsTile name={name} size={size} className={className} />
  }

  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={clsx('shrink-0 border border-hairline object-cover', SIZE_PX[size], className)}
    />
  )
}
