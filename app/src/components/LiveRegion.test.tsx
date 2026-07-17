import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { LiveRegion } from './LiveRegion';

describe('LiveRegion', () => {
  it('announces politely by default via role=status and aria-live=polite', () => {
    render(<LiveRegion message="Draft saved" />);
    const region = screen.getByRole('status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveTextContent('Draft saved');
  });

  it('switches to role=alert and aria-live=assertive when assertive', () => {
    render(<LiveRegion message="Connection lost" assertive />);
    const region = screen.getByRole('alert');
    expect(region).toHaveAttribute('aria-live', 'assertive');
    expect(region).toHaveTextContent('Connection lost');
  });

  it('stays mounted (not display:none) so screen readers can pick up updates', () => {
    render(<LiveRegion message="Saved" />);
    const region = screen.getByRole('status');
    expect(region).not.toHaveStyle({ display: 'none' });
  });

  it('renders no announcement text when message is empty', () => {
    render(<LiveRegion message="" />);
    expect(screen.getByRole('status')).toHaveTextContent('');
  });

  it('has zero axe violations (polite)', async () => {
    const { container } = render(<LiveRegion message="Draft saved" />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has zero axe violations (assertive)', async () => {
    const { container } = render(<LiveRegion message="Connection lost" assertive />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
