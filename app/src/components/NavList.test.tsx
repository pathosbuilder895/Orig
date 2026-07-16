import { fireEvent, render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { NavList } from './NavList';
import type { NavItem } from './NavList';

const items: NavItem[] = [
  { id: 'roster', label: 'Roster', href: '/roster' },
  { id: 'baselines', label: 'Baselines', href: '/baselines', current: true },
  { id: 'imports', label: 'Imports', href: '/imports' },
];

describe('NavList', () => {
  it('renders a nav landmark with the given accessible name', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    expect(screen.getByRole('navigation', { name: 'Course sections' })).toBeInTheDocument();
  });

  it('renders each item as a link inside a list', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const list = screen.getByRole('list');
    expect(list.querySelectorAll('li')).toHaveLength(3);
    for (const item of items) {
      expect(screen.getByRole('link', { name: String(item.label) })).toBeInTheDocument();
    }
  });

  it('marks the current item with aria-current=page, and no other item', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    expect(screen.getByRole('link', { name: 'Baselines' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Roster' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: 'Imports' })).not.toHaveAttribute('aria-current');
  });

  it('starts the roving tabindex on the current item, with all others at -1', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    expect(screen.getByRole('link', { name: 'Roster' })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('link', { name: 'Baselines' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('link', { name: 'Imports' })).toHaveAttribute('tabindex', '-1');
  });

  it('defaults the roving tabindex to the first item when none is current', () => {
    const noCurrent = items.map((item) => ({ ...item, current: false }));
    render(<NavList items={noCurrent} aria-label="Course sections" />);
    expect(screen.getByRole('link', { name: 'Roster' })).toHaveAttribute('tabindex', '0');
  });

  it('ArrowDown moves focus to the next item and updates the roving tabindex', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const baselines = screen.getByRole('link', { name: 'Baselines' });
    const imports = screen.getByRole('link', { name: 'Imports' });
    baselines.focus();

    fireEvent.keyDown(baselines, { key: 'ArrowDown' });

    expect(document.activeElement).toBe(imports);
    expect(imports).toHaveAttribute('tabindex', '0');
    expect(baselines).toHaveAttribute('tabindex', '-1');
  });

  it('ArrowUp wraps from the first item to the last', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const roster = screen.getByRole('link', { name: 'Roster' });
    const importsLink = screen.getByRole('link', { name: 'Imports' });
    fireEvent.focus(roster);

    fireEvent.keyDown(roster, { key: 'ArrowUp' });

    expect(document.activeElement).toBe(importsLink);
  });

  it('ArrowDown wraps from the last item to the first', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const importsLink = screen.getByRole('link', { name: 'Imports' });
    const roster = screen.getByRole('link', { name: 'Roster' });
    fireEvent.focus(importsLink);

    fireEvent.keyDown(importsLink, { key: 'ArrowDown' });

    expect(document.activeElement).toBe(roster);
  });

  it('Home and End jump to the first and last items', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const baselines = screen.getByRole('link', { name: 'Baselines' });
    baselines.focus();

    fireEvent.keyDown(baselines, { key: 'End' });
    expect(document.activeElement).toBe(screen.getByRole('link', { name: 'Imports' }));

    fireEvent.keyDown(screen.getByRole('link', { name: 'Imports' }), { key: 'Home' });
    expect(document.activeElement).toBe(screen.getByRole('link', { name: 'Roster' }));
  });

  it('updates the roving tabindex when a link receives focus directly (e.g. via Tab)', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const imports = screen.getByRole('link', { name: 'Imports' });
    fireEvent.focus(imports);
    expect(imports).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('link', { name: 'Baselines' })).toHaveAttribute('tabindex', '-1');
  });

  it('has zero axe violations', async () => {
    const { container } = render(<NavList items={items} aria-label="Course sections" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
