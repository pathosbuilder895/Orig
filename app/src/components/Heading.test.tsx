import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { CardTitle, PageTitle, Section } from './Heading';

describe('Heading primitives', () => {
  it('PageTitle always renders a real h1', () => {
    render(<PageTitle>Course Dashboard</PageTitle>);
    expect(screen.getByRole('heading', { level: 1, name: 'Course Dashboard' })).toBeInTheDocument();
  });

  it('a standalone CardTitle (no ambient context) defaults to h2', () => {
    render(<CardTitle>Roster</CardTitle>);
    expect(screen.getByRole('heading', { level: 2, name: 'Roster' })).toBeInTheDocument();
  });

  it('a CardTitle directly under PageTitle (no Section) is also h2', () => {
    render(
      <div>
        <PageTitle>Course Dashboard</PageTitle>
        <CardTitle>Roster</CardTitle>
      </div>,
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Course Dashboard');
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Roster');
  });

  it('wrapping content in Section pushes a nested CardTitle one level deeper', () => {
    render(
      <div>
        <PageTitle>Course Dashboard</PageTitle>
        <CardTitle>Roster</CardTitle>
        <Section>
          <CardTitle>Roster detail</CardTitle>
        </Section>
      </div>,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Roster');
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Roster detail');
  });

  it('nested Sections compose to keep descending one level at a time', () => {
    render(
      <div>
        <PageTitle>Course Dashboard</PageTitle>
        <Section>
          <CardTitle>Level 3</CardTitle>
          <Section>
            <CardTitle>Level 4</CardTitle>
          </Section>
        </Section>
      </div>,
    );
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Level 3');
    expect(screen.getByRole('heading', { level: 4 })).toHaveTextContent('Level 4');
  });

  it('clamps at h6 rather than producing an invalid heading level', () => {
    render(
      <Section>
        <Section>
          <Section>
            <Section>
              <Section>
                <CardTitle>Very deep</CardTitle>
              </Section>
            </Section>
          </Section>
        </Section>
      </Section>,
    );
    // 2 (default) + 5 Section wraps = 7, clamped to 6.
    expect(screen.getByRole('heading', { level: 6 })).toHaveTextContent('Very deep');
  });

  it('the level prop overrides the ambient context as an escape hatch', () => {
    render(
      <div>
        <PageTitle>Course Dashboard</PageTitle>
        <CardTitle level={4}>Forced level</CardTitle>
      </div>,
    );
    expect(screen.getByRole('heading', { level: 4 })).toHaveTextContent('Forced level');
  });

  it('has zero axe violations, including no skipped heading levels, across a composed hierarchy', async () => {
    const { container } = render(
      <div>
        <PageTitle>Course Dashboard</PageTitle>
        <CardTitle>Roster</CardTitle>
        <Section>
          <CardTitle>Roster detail</CardTitle>
          <Section>
            <CardTitle>Even deeper</CardTitle>
          </Section>
        </Section>
      </div>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
