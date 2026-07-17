import { fireEvent, render, screen, within } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import { DataTable } from './DataTable';
import type { DataTableColumn } from './DataTable';

interface Student {
  id: string;
  name: string;
  score: number;
}

const students: Student[] = [
  { id: 's2', name: 'Priya', score: 88 },
  { id: 's1', name: 'Amir', score: 95 },
  { id: 's3', name: 'Zoe', score: 72 },
];

const columns: DataTableColumn<Student>[] = [
  { key: 'name', header: 'Name', accessor: (row) => row.name, sortable: true },
  { key: 'score', header: 'Score', accessor: (row) => row.score, sortable: true },
  { key: 'notes', header: 'Notes', accessor: () => '', render: () => 'n/a' },
];

function nameColumnCells() {
  return screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent);
}

describe('DataTable', () => {
  it('renders a real table with column headers as scope=col', () => {
    render(
      <DataTable
        columns={columns}
        rows={students}
        getRowKey={(row) => row.id}
        caption="Students"
      />,
    );
    expect(screen.getByRole('table', { name: 'Students' })).toBeInTheDocument();
    for (const label of ['Name', 'Score', 'Notes']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(label) })).toHaveAttribute(
        'scope',
        'col',
      );
    }
  });

  it('renders rows in their original order before any sort is applied', () => {
    render(<DataTable columns={columns} rows={students} getRowKey={(row) => row.id} />);
    expect(nameColumnCells()).toEqual(['Priya', 'Amir', 'Zoe']);
  });

  it('makes sortable column headers real buttons', () => {
    render(<DataTable columns={columns} rows={students} getRowKey={(row) => row.id} />);
    expect(screen.getByRole('button', { name: /Name/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Score/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Notes/ })).not.toBeInTheDocument();
  });

  it('sorts ascending then descending then clears on repeated clicks, updating aria-sort', () => {
    render(<DataTable columns={columns} rows={students} getRowKey={(row) => row.id} />);
    const nameHeader = screen.getByRole('columnheader', { name: /Name/ });
    const sortButton = within(nameHeader).getByRole('button');

    fireEvent.click(sortButton);
    expect(nameHeader).toHaveAttribute('aria-sort', 'ascending');
    expect(nameColumnCells()).toEqual(['Amir', 'Priya', 'Zoe']);

    fireEvent.click(sortButton);
    expect(nameHeader).toHaveAttribute('aria-sort', 'descending');
    expect(nameColumnCells()).toEqual(['Zoe', 'Priya', 'Amir']);

    fireEvent.click(sortButton);
    expect(nameHeader).toHaveAttribute('aria-sort', 'none');
    expect(nameColumnCells()).toEqual(['Priya', 'Amir', 'Zoe']);
  });

  it('sorts numeric columns numerically, not lexicographically', () => {
    render(<DataTable columns={columns} rows={students} getRowKey={(row) => row.id} />);
    const scoreHeader = screen.getByRole('columnheader', { name: /Score/ });
    fireEvent.click(within(scoreHeader).getByRole('button'));
    const scores = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[1].textContent);
    expect(scores).toEqual(['72', '88', '95']);
  });

  it('has zero axe violations', async () => {
    const { container } = render(
      <DataTable
        columns={columns}
        rows={students}
        getRowKey={(row) => row.id}
        caption="Students"
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
