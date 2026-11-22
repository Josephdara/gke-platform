import type { Source } from '../api/types';
import { safeUrl } from '../links';

interface DocumentRow { key: string; title: string; url?: string; labels: string[]; sections: string[]; cited: boolean }

/** One row per document, linking to the original page at the best passage's section. */
function documents(sources: Source[], cited: string[]): DocumentRow[] {
  const rows = new Map<string, DocumentRow>();
  for (const source of sources) {
    const url = safeUrl(source.url);
    const key = url?.split('#')[0] ?? source.title;
    const row: DocumentRow = rows.get(key) ?? { key, title: source.title, url, labels: [], sections: [], cited: false };
    row.labels.push(source.label);
    if (source.headingPath && !row.sections.includes(source.headingPath)) row.sections.push(source.headingPath);
    row.cited ||= cited.includes(source.label);
    rows.set(key, row);
  }
  return [...rows.values()].sort((a, b) => Number(b.cited) - Number(a.cited));
}

export function Sources({ sources, cited }: { sources: Source[]; cited: string[] }) {
  const rows = documents(sources, cited);
  const heading = rows.some((row) => row.cited) ? 'Sources' : 'Related documentation';
  return <details className="sources">
    <summary><span className="sources-heading">{heading} <span className="sources-count">{rows.length}</span></span>
      <span className="sources-titles">{rows.map((row) => row.title).join(' · ')}</span></summary>
    <ul className="source-list">{rows.map((row) => <li key={row.key}>
      <span className="source-labels">{row.labels.join(' ')}</span>
      <span className="source-body">
        {row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer">{row.title}<span className="sr-only"> (opens in a new tab)</span></a> : <strong>{row.title}</strong>}
        {row.sections.length > 0 && <small>{row.sections.join(' · ')}</small>}
      </span>
    </li>)}</ul>
  </details>;
}
