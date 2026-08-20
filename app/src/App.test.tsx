import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('App', () => {
  it('renders the workspace placeholder inside the main landmark', () => {
    render(<App />);
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'main');
    expect(
      screen.getByRole('heading', { level: 1, name: /Original — app\/ workspace/ }),
    ).toBeInTheDocument();
  });

  it('has zero axe violations', async () => {
    const { container } = render(<App />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
