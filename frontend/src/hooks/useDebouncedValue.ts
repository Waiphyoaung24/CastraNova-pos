import { useEffect, useState } from "react"

const DEFAULT_DELAY_MS = 250

/**
 * Defers `value` by `delay`, so an expensive consumer (a filter over a complete
 * picker list, say) runs once the user stops typing rather than per keystroke.
 * The input itself stays controlled by the caller and remains instant.
 */
export function useDebouncedValue<T>(
  value: T,
  delay: number = DEFAULT_DELAY_MS,
): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return debounced
}
