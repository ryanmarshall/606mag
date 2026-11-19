// The contributor pages' text (pages/contributors): everyone the magazine credited, with every
// piece in publication order. Laid out like the all-articles page, in issue 12's frame.
import { articles, issueByNumber } from './content';
import { contributors, firstCopyOf, nameOf, summaryOf, type Contributor } from './seo';

const byId = new Map(articles.map((a) => [a.id, a]));
export const esc = (s: string) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

/** "by" -> "words" (a plain byline is a writer's); "illustration" -> "illustrations" */
const roleName = (role: string) => (role === 'by' ? 'words' : role === 'illustration' ? 'illustrations' : role);

/** One piece: its name linked, the issue and month, the credit, and (full) its summary. */
export function workLine(w: Contributor['works'][number], full: boolean): string {
  const a = byId.get(w.id)!;
  const issue = issueByNumber.get(a.issue)!;
  const head = `<a href="${firstCopyOf(a.url)}">${esc(nameOf(a))}</a> &middot; issue ${issue.number}: `
    + `<a href="${issue.url}">${esc(issue.name)}</a>, ${esc(issue.month.toLowerCase())} &middot; ${esc(roleName(w.role))}`;
  const summary = full ? summaryOf(w.id) : '';
  return summary ? `${head}<br>${esc(summary)}` : head;
}

/** Surname first for sorting ("stephanie mcniel" -> "mcniel stephanie"). */
const sortKey = (name: string) => {
  const parts = name.replace(/^jr\.\s+/, '').split(' ');
  return `${parts[parts.length - 1]} ${parts.slice(0, -1).join(' ')}`;
};
export const everyone = Object.entries(contributors).sort(([, a], [, b]) => sortKey(a.name).localeCompare(sortKey(b.name)));

/** What someone did, from their credits: "words and photos". */
export function rolesOf(c: Contributor): string {
  const words = [...new Set(c.roles.flatMap((r) => r.split(/\s+and\s+|\s*,\s*/)).map(roleName))];
  return words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}` : words[0];
}

/** The frame-width table every plain page uses (about, privacy, all articles). */
export function plainPage(inner: string): string {
  return '<table width="668" border="0" cellpadding="0" cellspacing="0" class="back"><tr><td align="center" valign="top">'
    + '<table cellpadding="0" cellspacing="0" class="bodytext"><tr><td class="left_margin"><p>'
    + inner + '</p></td></tr></table><p>&nbsp;</p></td></tr></table>';
}

/** /contributors/: everyone, surname order; people with their own page link to it, everyone
 *  else's pieces are listed here in full. */
export function contributorsBody(): string {
  const blocks = everyone.map(([slug, c]) => {
    const n = c.works.length;
    const name = c.page ? `<a href="/contributors/${slug}/">${esc(c.name)}</a>` : esc(c.name);
    const head = `<a name="${slug}" id="${slug}"></a><b>${name}</b> &middot; ${esc(rolesOf(c))} &middot; ${n} piece${n === 1 ? '' : 's'}`;
    const lines = c.page ? [] : c.works.map((w) => workLine(w, true));
    return [head, ...lines].join('<br>') + '<br><br>';
  });
  return plainPage('<span class="style6">contributors</span><br><br>'
    + `The ${everyone.length} writers, photographers and illustrators of sixosix, credited as the magazine credited them, `
    + 'and what each made for it in 2004. A name with a link has its own page listing all of that person&rsquo;s work.<br><br>'
    + blocks.join('') + '<a href="/articles/">every article, issue by issue</a>');
}

/** /contributors/<slug>/: what one person did and every piece, with its opening lines. */
export function contributorBody(c: Contributor): string {
  return plainPage(`<span class="style6">${esc(c.name)}</span><br><br>`
    + `${esc(rolesOf(c))} for sixosix, ${c.works.length} pieces in 2004.<br><br>`
    + c.works.map((w) => workLine(w, true)).join('<br><br>')
    + '<br><br><a href="/contributors/">all contributors</a> &middot; <a href="/articles/">every article, issue by issue</a>');
}
