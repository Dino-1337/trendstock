import { Search } from 'lucide-react'

// A real, working search box — scoped to the list it filters (Trends,
// Catalog), rather than a global topbar search with nothing to act on.
export default function SearchInput({ value, onChange, placeholder = 'Search' }) {
  return (
    <label className="relative block w-full max-w-[140px] sm:max-w-[220px]">
      <Search size={14} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-pill border border-hairline bg-cream py-2 pl-9 pr-3 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-pastel-purple"
      />
    </label>
  )
}
