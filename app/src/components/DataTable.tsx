import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import './DataTable.css';

export type SortDirection = 'ascending' | 'descending';

export interface DataTableColumn<T> {
  /** Stable identifier for the column; also the sort key. */
  key: string;
  /** Visible column header text. */
  header: ReactNode;
  /** Raw, comparable value for this column — used for sorting and, absent `render`, for display. */
  accessor: (row: T) => string | number;
  /** Optional custom cell rendering; falls back to `accessor`'s value. */
  render?: (row: T) => ReactNode;
  /** Whether this column's header is a sort button. Requires `accessor` to return a comparable value. */
  sortable?: boolean;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  /** Stable key per row, for React's list reconciliation. */
  getRowKey: (row: T, index: number) => string;
  caption?: ReactNode;
}

interface SortState {
  key: string;
  direction: SortDirection;
}

/**
 * A semantic, sortable data table (WS-8 R2 primitive, fixes durable W7 —
 * replaces CSS-grid-of-divs table look-alikes). Renders a real <table> with
 * <th scope="col">, and sortable column headers as real <button>s, which
 * are keyboard-operable (Enter/Space) by virtue of being native buttons —
 * no custom key handling required. Sort state is reflected to assistive
 * tech via aria-sort on the <th>.
 */
export function DataTable<T>({ columns, rows, getRowKey, caption }: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState | null>(null);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((candidate) => candidate.key === sort.key);
    if (!column) return rows;

    const factor = sort.direction === 'ascending' ? 1 : -1;
    return [...rows].sort((a, b) => {
      const valueA = column.accessor(a);
      const valueB = column.accessor(b);
      if (typeof valueA === 'number' && typeof valueB === 'number') {
        return (valueA - valueB) * factor;
      }
      return String(valueA).localeCompare(String(valueB)) * factor;
    });
  }, [rows, sort, columns]);

  function handleSort(key: string) {
    setSort((previous) => {
      if (!previous || previous.key !== key) return { key, direction: 'ascending' };
      if (previous.direction === 'ascending') return { key, direction: 'descending' };
      return null;
    });
  }

  return (
    <table className="data-table">
      {caption ? <caption className="data-table-caption">{caption}</caption> : null}
      <thead>
        <tr>
          {columns.map((column) => {
            const isSorted = sort?.key === column.key;
            const direction = isSorted ? sort.direction : undefined;

            return (
              <th
                key={column.key}
                scope="col"
                aria-sort={column.sortable ? (direction ?? 'none') : undefined}
              >
                {column.sortable ? (
                  <button
                    type="button"
                    className="data-table-sort-button"
                    onClick={() => handleSort(column.key)}
                  >
                    {column.header}
                    <span className="data-table-sort-indicator" aria-hidden="true">
                      {direction === 'ascending' ? '▲' : direction === 'descending' ? '▼' : '⇅'}
                    </span>
                  </button>
                ) : (
                  column.header
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {sortedRows.map((row, index) => (
          <tr key={getRowKey(row, index)}>
            {columns.map((column) => (
              <td key={column.key}>{column.render ? column.render(row) : column.accessor(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
