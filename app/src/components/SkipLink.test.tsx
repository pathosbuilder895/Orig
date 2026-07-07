import { render } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { SkipLink } from './SkipLink';

describe('SkipLink', () => {
  it('has zero axe violations', async () => {
    const { container } = render(
      <div>
        <SkipLink />
        <main id="main">content</main>
      </div>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
