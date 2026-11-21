import { useState } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Source } from '../api/types';
import { safeUrl } from '../links';

/** The shape shared by the Markdown and HTML syntax trees, as far as this file reads them. */
interface HastNode { type: string; value?: string; children?: HastNode[] }

function textOf(node: HastNode | undefined): string {
  if (!node) return '';
  return node.type === 'text' ? node.value ?? '' : (node.children ?? []).map(textOf).join('');
}

/** Shows raw HTML as the text it is. Dropping it instead would lose placeholders such as <pod-name>. */
function htmlAsText() {
  const walk = (node: HastNode) => {
    if (node.type === 'html') node.type = 'text';
    node.children?.forEach(walk);
  };
  return (tree: unknown) => { walk(tree as HastNode); };
}

/** Rewrites [S1] outside code into a #cite- link, which the renderer shows as a citation. */
export function linkCitations(markdown: string): string {
  return markdown.split(/(```[\s\S]*?(?:```|$))/g)
    .map((part, index) => index % 2 ? part
      : part.replace(/`[^`\n]*`|\[(S\d{1,3})\](?!\()/g, (match, label?: string) => label ? `[${label}](#cite-${label})` : match))
    .join('');
}

function CodeBlock({ code, children }: { code: string; children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(code.replace(/\n$/, ''));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2_000);
    } catch { setCopied(false); }
  }
  return <div className="code-block">
    <button type="button" className="code-copy" onClick={() => { void copy(); }}>{copied ? 'Copied' : 'Copy'}</button>
    <pre>{children}</pre>
  </div>;
}

interface MarkdownProps {
  content: string;
  sources: Source[];
  /** Labels checked against the answer's sources; before the check finishes, none are linked. */
  valid: string[];
  invalid: string[];
}

/** Model output as Markdown. Raw HTML stays text, images are dropped, and only http(s) links open. */
export function Markdown({ content, sources, valid, invalid }: MarkdownProps) {
  const components: Components = {
    a({ href, children }) {
      const cited = href?.startsWith('#cite-') ? href.slice('#cite-'.length) : undefined;
      if (cited) {
        if (invalid.includes(cited)) return <span className="unverified">[{cited}: unverified citation]</span>;
        const source = sources.find((entry) => entry.label === cited);
        const url = safeUrl(source?.url);
        if (!source || !valid.includes(cited)) return <span className="citation-pending">[{cited}]</span>;
        return url
          ? <a className="citation" href={url} target="_blank" rel="noopener noreferrer" title={`${source.title}: ${source.headingPath}`}>{cited}<span className="sr-only"> (opens {source.title} in a new tab)</span></a>
          : <span className="citation" title={source.title}>{cited}</span>;
      }
      const url = safeUrl(href);
      return url ? <a href={url} target="_blank" rel="noopener noreferrer">{children}</a> : <>{children}</>;
    },
    pre({ node, children }) {
      return <CodeBlock code={textOf(node as HastNode | undefined)}>{children}</CodeBlock>;
    },
  };
  return <div className="answer-text markdown">
    <ReactMarkdown remarkPlugins={[remarkGfm, htmlAsText]} disallowedElements={['img']} components={components}>{linkCitations(content)}</ReactMarkdown>
  </div>;
}
