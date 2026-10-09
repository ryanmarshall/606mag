import { defineMiddleware } from 'astro:middleware';

// The 2004 pages were laid out by browsers in their legacy modes, which change table
// font sizes, the gaps under images in table cells and percentage heights. Astro always
// emits <!DOCTYPE html> (standards mode), so swap in the doctype each original page had:
// magazine pages had none (quirks mode; this public id without a system id selects it),
// and the final front page declared HTML 4.01 Transitional with its DTD (limited quirks).
const QUIRKS = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">';
const LIMITED_QUIRKS = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">';

export const onRequest = defineMiddleware(async (context, next) => {
  const response = await next();
  const path = context.url.pathname.replace(/^\/606mag(?=\/)/, '');
  const doctype = path === '/' ? LIMITED_QUIRKS : path.startsWith('/issues/') ? QUIRKS : null;
  if (!doctype || !(response.headers.get('content-type') ?? '').includes('text/html')) return response;
  const html = (await response.text()).replace(/^\s*<!doctype html>/i, doctype);
  return new Response(html, { status: response.status, statusText: response.statusText, headers: response.headers });
});
