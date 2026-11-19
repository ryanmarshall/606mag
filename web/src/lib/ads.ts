// Which pages carry the right-hand Google ads (components/AdRight.astro).
import adsData from '../data/ads.json';
import { articles, issues } from './content';
import { ADSENSE_CLIENT, ADSENSE_SLOT } from '../config';
import { firstCopyOf } from './seo';

const noAds = new Map((adsData.noAds as { url: string; why: string }[]).map((e) => [e.url, e.why]));
const known = new Set([...issues.map((i) => i.url), ...articles.flatMap((a) => [a.url, ...a.pages.map((p) => p.url)])]);
for (const url of noAds.keys()) {
  if (!known.has(url)) throw new Error(`data/ads.json: ${url} is not an issue cover, article or article page`);
}

// A single photo's page (".../img-3/") is a picture and the article's menu, with no writing
// of its own beside the ads, and a page published twice is the same writing again (its
// canonical is the first copy); neither carries ads (AdSense: no ads on screens without
// publisher content or with replicated content).
const PHOTO_PAGE = /\/img-[^/]+\/$/;

/** Whether an issue cover or article page shows the ad column. */
export function showAds(pageUrl: string, articleUrl?: string): boolean {
  if (!ADSENSE_CLIENT || !ADSENSE_SLOT) return false;
  if (PHOTO_PAGE.test(pageUrl) || firstCopyOf(pageUrl) !== pageUrl) return false;
  return !noAds.has(pageUrl) && !(articleUrl && noAds.has(articleUrl));
}
