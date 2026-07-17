import { useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import './NavList.css';

export interface NavItem {
  /** Stable identifier for the item, used as React's list key. */
  id: string;
  label: ReactNode;
  href: string;
  /** Marks this item as the current page — rendered with aria-current="page". */
  current?: boolean;
}

export interface NavListProps {
  items: NavItem[];
  /** Accessible name for the <nav> landmark (there is no visible default — a page can have several navs). */
  'aria-label': string;
  className?: string;
}

/**
 * A keyboard-navigable navigation list (WS-8 R2 primitive, fixes durable
 * W1): a real <nav><ul><li><a> structure — screen readers get landmark
 * semantics and "list of N items" for free — with a roving-tabindex
 * arrow-key pattern layered on top, per the WAI-ARIA APG navigation pattern.
 * Only one link is ever a Tab stop at a time (tabIndex=0); ArrowDown/Up
 * (and Right/Left, for a horizontal nav) move both DOM focus and the roving
 * index; Home/End jump to the first/last item. The current page is marked
 * via aria-current="page" rather than a class alone, so assistive tech
 * announces it, not just sighted users via CSS.
 */
export function NavList({ items, className, 'aria-label': ariaLabel }: NavListProps) {
  const currentIndex = items.findIndex((item) => item.current);
  const [activeIndex, setActiveIndex] = useState(currentIndex >= 0 ? currentIndex : 0);
  const linkRefs = useRef<(HTMLAnchorElement | null)[]>([]);

  function focusItem(index: number) {
    if (items.length === 0) return;
    const wrapped = (index + items.length) % items.length;
    setActiveIndex(wrapped);
    linkRefs.current[wrapped]?.focus();
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLAnchorElement>, index: number) {
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowRight':
        event.preventDefault();
        focusItem(index + 1);
        break;
      case 'ArrowUp':
      case 'ArrowLeft':
        event.preventDefault();
        focusItem(index - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusItem(0);
        break;
      case 'End':
        event.preventDefault();
        focusItem(items.length - 1);
        break;
      default:
        break;
    }
  }

  return (
    <nav aria-label={ariaLabel} className={className}>
      <ul className="nav-list">
        {items.map((item, index) => (
          <li key={item.id}>
            <a
              ref={(node) => {
                linkRefs.current[index] = node;
              }}
              href={item.href}
              className="nav-list-link"
              aria-current={item.current ? 'page' : undefined}
              tabIndex={index === activeIndex ? 0 : -1}
              onFocus={() => setActiveIndex(index)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
