// Public IDs for Google's tags. They appear in every page's source by design, so they are not
// secrets (never put anything private here). Empty = that tag is not emitted at all.
// Fill in the defaults below once the accounts exist; test builds can override them:
//   PUBLIC_GA4_ID=G-TEST0000 PUBLIC_ADSENSE_CLIENT=ca-pub-0000000000000000 PUBLIC_ADSENSE_SLOT=0000000000 PUBLIC_ADTEST=on npm run build
// When you fill in or change an ID, also update POLICY_UPDATED: the privacy page's wording follows them.
//
// GO-LIVE: Google account settings this code relies on (nothing in the build can check them):
//  1. AdSense > Privacy & messaging > European regulations: create and publish a message for 606mag.com
//     (privacy policy URL https://606mag.com/privacy/), and on its Settings page turn ON both consent-mode
//     settings (off by default). Until then an EEA/UK/CH visitor's "consent" never reaches Google Analytics.
//  2. Optional: AdSense > Privacy & messaging > US state regulations: publish a message, then set
//     US_STATES_MESSAGE = true below (the privacy page mentions the opt-out only then).
//  3. AdSense > Ads: keep Auto ads OFF (otherwise Google places ads on phones and pages without the column).
//  4. GA4 keeps visit-level data for its default 2 months; the privacy page says so. If you change Admin >
//     Data collection and modification > Data retention, change that sentence in pages/privacy.astro.
//  5. After deploying, check from an EEA connection that the consent message shows on an /issues/ page,
//     an /archive/ page and /privacy/, and that "privacy and cookie settings" on /privacy/ reopens it.
const env = import.meta.env;
const pick = (v: unknown, fallback: string): string => (typeof v === 'string' ? v.trim() : fallback);

/** Google Analytics 4 measurement ID, e.g. 'G-XXXXXXXXXX' */
export const GA4_ID = pick(env.PUBLIC_GA4_ID, 'G-ZVKBSPGJ08');
/** AdSense publisher ID, e.g. 'ca-pub-0123456789012345' */
export const ADSENSE_CLIENT = pick(env.PUBLIC_ADSENSE_CLIENT, 'ca-pub-9710988980113135');
/** the 160x600 display unit's ID (data-ad-slot); both units in the column use it */
export const ADSENSE_SLOT = pick(env.PUBLIC_ADSENSE_SLOT, '7717182726');
/** data-adtest="on": test ads that earn nothing, for checking a build */
export const ADTEST = env.PUBLIC_ADTEST === 'on';
/** the site owner's address, shown on the privacy page */
export const CONTACT_EMAIL = 'rmarsh000@gmail.com';
/** the privacy page's "Last updated" date */
export const POLICY_UPDATED = 'October 21, 2026';
/** true only once a US state regulations message is published in AdSense Privacy & messaging */
export const US_STATES_MESSAGE = false;

// The IDs are written into inline scripts, so only exact formats get through.
const check = (value: string, re: RegExp, name: string) => {
  if (value && !re.test(value)) throw new Error(`config.ts: ${name} doesn't look right: ${value}`);
};
check(GA4_ID, /^G-[A-Z0-9]{4,16}$/, 'GA4_ID');
check(ADSENSE_CLIENT, /^ca-pub-\d{16}$/, 'ADSENSE_CLIENT');
check(ADSENSE_SLOT, /^\d{6,12}$/, 'ADSENSE_SLOT');

/** the publisher ID as ads.txt and the consent message tag write it: pub-… */
export const PUB_ID = ADSENSE_CLIENT.replace(/^ca-/, '');
