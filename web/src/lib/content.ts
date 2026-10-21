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
  /** the issue menu's sections, in order, with their articles' ids */
  sections: { name: string; articles: number[] }[];
}

export const issues = issuesData as Issue[];
export const articles = articlesData as Article[];
export const issueByNumber = new Map(issues.map((i) => [i.number, i]));

const OLD_PRIVACY = 'href="/archive/main/general-footer_page-privacy.html"';
const MENU = '<div id="footer_menu">';
/** The footer menu's first link, added in 2026: what this site is (pages/about.astro). */
export const ABOUT_LINK = '<a href="/about/">about this archive</a>      |      ';
/** The issue's footer: "about this archive" leads the menu, and its "privacy policy" link opens
 *  the current policy (the 2004 one stays in the archive). */
export function footerOf(issue: Issue): string {
  if (!issue.frame.footer.includes(OLD_PRIVACY)) throw new Error(`issue ${issue.number}: the footer's privacy link moved`);
  if (!issue.frame.footer.includes(MENU)) throw new Error(`issue ${issue.number}: the footer menu moved`);
  return issue.frame.footer.replace(OLD_PRIVACY, 'href="/privacy/"').replace(MENU, MENU + ABOUT_LINK);
}

/** Attributes of the original content cell, as a props object for Astro. */
export function attrs(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of raw.matchAll(/([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g)) {
    out[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? '';
  }
  return out;
}
