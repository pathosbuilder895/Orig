import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { Chart } from './Chart';

describe('Chart', () => {
  it('exposes the required summary as the accessible name via role=img + aria-label', () => {
    render(
      <Chart summary="Voice consistency: 82 percent, steady over the last 5 submissions.">
        <svg data-testid="voice-radar" />
      </Chart>,
    );
    expect(
      screen.getByRole('img', {
        name: 'Voice consistency: 82 percent, steady over the last 5 submissions.',
      }),
    ).toBeInTheDocument();
  });

  it('hides the raw visual from the accessibility tree so its content is not read separately', () => {
    render(
      <Chart summary="Voice consistency: 82 percent.">
        <svg data-testid="voice-radar" />
      </Chart>,
    );
    const visual = screen.getByTestId('voice-radar');
    expect(visual.closest('[aria-hidden="true"]')).not.toBeNull();
  });

  it('renders no describedby link when no details fallback is given', () => {
    render(
      <Chart summary="Voice consistency: 82 percent.">
        <svg />
      </Chart>,
    );
    expect(screen.getByRole('img')).not.toHaveAttribute('aria-describedby');
  });

  it('links an optional visually-hidden details table via aria-describedby', () => {
    render(
      <Chart
        summary="Voice consistency over time."
        details={
          <table>
            <caption>Voice consistency by submission</caption>
            <tbody>
              <tr>
                <th scope="row">Submission 1</th>
                <td>78%</td>
              </tr>
              <tr>
                <th scope="row">Submission 2</th>
                <td>82%</td>
              </tr>
            </tbody>
          </table>
        }
      >
        <svg />
      </Chart>,
    );
    const chart = screen.getByRole('img');
    const describedById = chart.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    const detailsEl = document.getElementById(describedById!);
    expect(detailsEl).not.toBeNull();
    expect(detailsEl).not.toHaveStyle({ display: 'none' });
    expect(screen.getByText('Submission 1')).toBeInTheDocument();
  });

  it('has zero axe violations in the base state', async () => {
    const { container } = render(
      <Chart summary="Voice consistency: 82 percent.">
        <svg />
      </Chart>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has zero axe violations with a details fallback', async () => {
    const { container } = render(
      <Chart
        summary="Voice consistency over time."
        details={
          <ul>
            <li>Submission 1: 78%</li>
            <li>Submission 2: 82%</li>
          </ul>
        }
      >
        <svg />
      </Chart>,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
