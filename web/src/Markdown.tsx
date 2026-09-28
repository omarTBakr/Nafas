import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * A model's reply, rendered as Markdown: emphasis, lists, headings, tables.
 *
 * Safe by construction: react-markdown builds React elements and never
 * renders raw HTML from the text, so a reply cannot inject markup or script.
 * Links open in a new tab, without handing it this page. Incomplete Markdown
 * (a reply still streaming in) renders as far as it has arrived.
 */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md" dir="auto">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
