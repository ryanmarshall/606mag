// What search engines and link previews read: each page's title, description, picture and
// structured data (schema.org JSON-LD). It all goes in <head>, so the pages look exactly the
// same. Titles, descriptions, pictures and credits come from data/seo.json (tools/make_seo.py).
import seoData from '../data/seo.json';
import { issueByNumber, type Article, type Issue, type Page } from './content';

export const SITE = 'https://606mag.com';
const MAGAZINE = `${SITE}/#magazine`;
const ORG = `${SITE}/#publisher`;

interface PageSeo {
  /** the page's own name (breadcrumbs); title adds the magazine and month */
  name?: string; title: string; description: string;
  /** a page published twice names its first copy (tools/make_seo.py) */
  canonical?: string;
  image?: string; imageWidth?: number; imageHeight?: number; imageAlt?: string;
}
interface Credit { role: string; name: string }
const data = seoData as unknown as {
  pages: Record<string, PageSeo>;
  articles: Record<string, { name: string; credits: Credit[]; teaser: string }>;
  people: Record<string, { name: string; age: number; jobTitle: string }[]>;
};

export interface Seo extends PageSeo {
  url: string;
  type: 'website' | 'article';
  jsonLd: object[];
}

function pageSeo(url: string): PageSeo {
  const p = data.pages[url];
  if (!p) throw new Error(`seo.json has no entry for ${url}: run tools/make_seo.py`);
  return p;
}
const abs = (path: string) => SITE + encodeURI(path);
/** "January 2004" -> "2004-01" */
function month(issue: Issue): string {
  const d = new Date(`1 ${issue.month} UTC`);
  if (Number.isNaN(d.getTime())) throw new Error(`issue ${issue.number}: unreadable month "${issue.month}"`);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}
const issueName = (issue: Issue) => `issue ${issue.number}: ${issue.name}`;

function crumbs(trail: [string, string][]): object {
  return {
    '@type': 'BreadcrumbList',
    itemListElement: trail.map(([name, url], i) => ({ '@type': 'ListItem', position: i + 1, name, item: SITE + url })),
  };
}

/** The magazine itself (front page). */
export function frontSeo(): Seo {
  const p = pageSeo('/');
  return {
    ...p, url: '/', type: 'website',
    jsonLd: [
      { '@type': 'WebSite', '@id': `${SITE}/#website`, url: `${SITE}/`, name: 'sixosix magazine',
        alternateName: ['sixosix', '606mag', '606mag.com'], inLanguage: 'en', about: { '@id': MAGAZINE } },
      { '@type': 'Organization', '@id': ORG, name: 'sixosix magazine', alternateName: '606mag', url: `${SITE}/`,
        location: { '@type': 'Place', name: 'Chicago, Illinois' } },
      { '@type': 'Periodical', '@id': MAGAZINE, name: 'sixosix magazine', alternateName: ['sixosix', '606mag'],
        url: `${SITE}/`, description: p.description, inLanguage: 'en', startDate: '2004-01', endDate: '2004-12',
        publisher: { '@id': ORG }, locationCreated: { '@type': 'Place', name: 'Chicago, Illinois' },
        ...(p.image ? { image: abs(p.image) } : {}) },
    ],
  };
}

export function issueSeo(issue: Issue, parts: Article[]): Seo {
  const p = pageSeo(issue.url);
  return {
    ...p, url: issue.url, type: 'website',
    jsonLd: [
      { '@type': 'PublicationIssue', '@id': `${SITE}${issue.url}#issue`, url: SITE + issue.url,
        name: `sixosix magazine, ${issueName(issue)}`, issueNumber: String(issue.number), datePublished: month(issue),
        inLanguage: 'en', isPartOf: { '@id': MAGAZINE }, publisher: { '@id': ORG },
        ...(p.image ? { image: abs(p.image) } : {}),
        hasPart: parts.filter((a) => !data.pages[a.url]?.canonical)
          .map((a) => ({ '@type': 'Article', '@id': `${SITE}${a.url}#article`, headline: nameOf(a), url: SITE + a.url })) },
      crumbs([['sixosix magazine', '/'], [issueName(issue), issue.url]]),
    ],
  };
}

// "words by", "novella by" and "by" name the writer; photos, illustrations and the like are
// contributions. A credit to the magazine's staff is the magazine itself, not a person.
const AUTHOR = /^(by|words|text|story|interview|written|novella)\b/;
const EDITOR = /^edited\b/;
const person = (c: Credit) => (c.name === 'sixosix staff' ? { '@id': ORG } : { '@type': 'Person', name: c.name });

export function articleSeo(article: Article, page: Page): Seo {
  const issue = issueByNumber.get(article.issue)!;
  const p = pageSeo(page.url);
  const credits = data.articles[String(article.id)]?.credits ?? [];
  const id = `${SITE}${article.url}#article`;
  const trail: [string, string][] = [['sixosix magazine', '/'], [issueName(issue), issue.url], [nameOf(article), article.url]];
  const jsonLd: object[] = [];
  if (page.url === article.url) {
    const first = pageSeo(article.url);
    const people = data.people[String(article.id)];
    const authors = credits.filter((c) => AUTHOR.test(c.role)).map(person);
    const editors = credits.filter((c) => EDITOR.test(c.role)).map(person);
    const others = credits.filter((c) => !AUTHOR.test(c.role) && !EDITOR.test(c.role)).map(person);
    jsonLd.push({
      '@type': 'Article', '@id': id, url: SITE + article.url, headline: nameOf(article).slice(0, 110),
      description: first.description, datePublished: month(issue), inLanguage: 'en',
      ...(article.section ? { articleSection: article.section } : {}),
      ...(authors.length ? { author: authors } : {}),
      ...(editors.length ? { editor: editors } : {}),
      ...(others.length ? { contributor: others } : {}),
      ...(first.image ? { image: abs(first.image) } : {}),
      ...(article.comments.length ? { commentCount: article.comments.length } : {}),
      ...(people ? { about: people.map((x) => ({ '@type': 'Person', name: x.name, jobTitle: x.jobTitle,
                                                description: `${x.jobTitle}, ${x.age}, in ${issue.month}` })) } : {}),
      isPartOf: { '@id': `${SITE}${issue.url}#issue` }, publisher: { '@id': ORG },
    });
  } else {
    jsonLd.push({ '@type': 'WebPage', '@id': SITE + page.url, url: SITE + page.url, name: p.name ?? p.title, inLanguage: 'en',
                  isPartOf: { '@id': id } });
    trail.push([p.name ?? p.title, page.url]);
  }
  jsonLd.push(crumbs(trail));
  return { ...p, url: page.url, type: 'article', jsonLd };
}

/** The page that says what this site is (pages/about.astro). */
export function aboutSeo(): Seo {
  const p = pageSeo('/about/');
  return {
    ...p, url: '/about/', type: 'website',
    jsonLd: [
      { '@type': 'AboutPage', '@id': `${SITE}/about/`, url: `${SITE}/about/`, name: p.name ?? p.title,
        description: p.description, inLanguage: 'en', about: { '@id': MAGAZINE }, isPartOf: { '@id': `${SITE}/#website` } },
      crumbs([['sixosix magazine', '/'], ['about this archive', '/about/']]),
    ],
  };
}

/** Every article, issue by issue (pages/articles.astro). */
export function articlesSeo(): Seo {
  const p = pageSeo('/articles/');
  return {
    ...p, url: '/articles/', type: 'website',
    jsonLd: [
      { '@type': 'CollectionPage', '@id': `${SITE}/articles/`, url: `${SITE}/articles/`, name: p.name ?? p.title,
        description: p.description, inLanguage: 'en', about: { '@id': MAGAZINE }, isPartOf: { '@id': `${SITE}/#website` } },
      crumbs([['sixosix magazine', '/'], ['all articles', '/articles/']]),
    ],
  };
}

/** An article's byline as one phrase ("words by tom hardman, photos by douglas fogelson"). */
export function creditsOf(id: number): string {
  const credits = data.articles[String(id)]?.credits ?? [];
  const roles = [...new Set(credits.map((c) => c.role))];
  return roles.map((r) => `${r === 'by' ? 'by' : `${r} by`} ${credits.filter((c) => c.role === r).map((c) => c.name).join(' and ')}`).join(', ');
}

/** An article's name as its issue menu shows it (tools/make_seo.py display_name). */
export function nameOf(article: Article): string {
  return data.articles[String(article.id)]?.name ?? article.title;
}

/** The first copy of a page published twice (its canonical address), else the page itself. */
export function firstCopyOf(url: string): string {
  return data.pages[url]?.canonical ?? url;
}

export function plainSeo(url: string): Seo {
  return { ...pageSeo(url), url, type: 'website', jsonLd: [] };
}

/** The JSON-LD block's text: one @graph, safe inside a <script> element. */
export function jsonLdText(items: object[]): string {
  return JSON.stringify({ '@context': 'https://schema.org', '@graph': items }).replace(/</g, '\\u003c');
}
export { abs as absoluteUrl };
