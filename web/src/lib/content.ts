// Content extracted from the recovered site by tools/extract_content.py, exactly as last published.
import issuesData from '../data/issues.json';
import articlesData from '../data/articles.json';

export interface Page {
  path: string; url: string; mainAttrs: string; html: string; css: string;
  /** the menu's "new comments" box as this page's own capture showed it (null: the issue's) */
  newComments: string | null;
  /** whether the original page showed the comments block */
  comments: boolean;
  /** article markup that followed the comments block on the original page */
  tail?: string;
}
export interface Comment { date: string; name: string; subject: string; text: string }
export interface Article {
  id: number; title: string; menuTitle: string; slug: string; issue: number; section: string | null;
  folder: string; issueFolder: string; url: string; blurb: string | null; pageTitle?: string;
  pages: Page[]; comments: Comment[]; views: number;
}
export interface Frame { issues: string; nav: string; menu: string; footer: string; newComments: string }
/** Where the issue menu's "new comments" box goes (tools/extract_content.py). */
export const NEW_COMMENTS_SLOT = '<!--new comments-->';
export interface Issue {
  number: number; name: string; folder: string; colorDark: string; colorLight: string; commentColor: string; month: string;
  url: string; title: string; frame: Frame; themeCss: string; coverAttrs: string; coverHtml: string; coverCss: string;
}

export const issues = issuesData as Issue[];
export const articles = articlesData as Article[];
export const issueByNumber = new Map(issues.map((i) => [i.number, i]));

/** Attributes of the original content cell, as a props object for Astro. */
export function attrs(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of raw.matchAll(/([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g)) {
    out[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? '';
  }
  return out;
}
