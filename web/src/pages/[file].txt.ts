// ads.txt (IAB): who may sell this site's ad space. Written only once config.ts has the AdSense
// publisher ID (a placeholder line would be invalid).
import type { APIRoute } from 'astro';
import { PUB_ID } from '../config';
export function getStaticPaths() {
  return PUB_ID ? [{ params: { file: 'ads' } }] : [];
}
export const GET: APIRoute = () =>
  new Response(`google.com, ${PUB_ID}, DIRECT, f08c47fec0942fa0\n`, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
