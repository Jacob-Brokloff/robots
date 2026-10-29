/**
 * A CSS selector a reader (or an agent fixing the issue) can paste into devtools to find the element
 * a reviewer pointed at. Short and readable beats unique: an id ends the path, otherwise up to four
 * levels of tag, a couple of classes and :nth-of-type where siblings share a tag.
 */
export function selectorOf(el: Element | null): string {
  const parts: string[] = []
  for (let node = el; node && node !== document.body && parts.length < 4; node = node.parentElement) {
    if (node.id) { parts.unshift(`#${CSS.escape(node.id)}`); break }
    let part = node.tagName.toLowerCase()
    const classes = [...node.classList].filter(c => !/^\d/.test(c)).slice(0, 2)
    if (classes.length) part += classes.map(c => `.${CSS.escape(c)}`).join('')
    const parent = node.parentElement
    if (parent) {
      const same = [...parent.children].filter(c => c.tagName === node!.tagName)
      if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`
    }
    parts.unshift(part)
  }
  return parts.join(' > ')
}

/** What the element says, for the issue: its accessible label or the start of its text. */
export function labelOf(el: Element | null): string {
  if (!el) return ''
  const text = el.getAttribute('aria-label') || el.getAttribute('title') || (el as HTMLElement).innerText || ''
  return text.replace(/\s+/g, ' ').trim().slice(0, 120)
}
