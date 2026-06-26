"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

// Citations from the agent arrive as markdown links whose href is a document id
// (for example DOC-ACC-1001-ST), which is not a real URL. Resolve those to the
// owning account's 360 view (where the document lives); send real URLs out in a
// new tab; render anything else as plain styled text so nothing is a dead link.
function MarkdownAnchor({ href, children, ...rest }: ComponentProps<"a">) {
  const target = href ?? "";
  if (/^https?:\/\//i.test(target)) {
    return (
      <a href={target} target="_blank" rel="noopener noreferrer" {...rest}>
        {children}
      </a>
    );
  }
  const account = target.match(/\b((?:ACC|AR)-\d+)\b/i);
  if (account) {
    return (
      <Link href={`/accounts/${account[1].toUpperCase()}`}>{children}</Link>
    );
  }
  return <span className="text-primary">{children}</span>;
}

// Renders assistant chat content as markdown, styled to the grayscale + Claude
// orange palette with Geist. Restrained spacing so it reads like a chat bubble,
// not a document.
export function Markdown({ content }: { content: string }) {
  return (
    <div
      className={cn(
        "space-y-2 text-sm leading-relaxed text-card-foreground",
        "[&_strong]:font-semibold [&_strong]:text-foreground",
        "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
        "[&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5",
        "[&_ol]:list-decimal [&_ol]:space-y-1 [&_ol]:pl-5",
        "[&_li]:marker:text-muted-foreground",
        "[&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold",
        "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12px]",
        "[&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:border-border [&_pre]:bg-muted [&_pre]:p-3",
        "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
        "[&_blockquote]:border-l-2 [&_blockquote]:border-primary [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1",
        "[&_hr]:my-3 [&_hr]:border-border",
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: MarkdownAnchor }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default Markdown;
