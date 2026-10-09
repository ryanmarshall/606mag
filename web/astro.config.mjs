// @ts-check
import { defineConfig } from 'astro/config';

// Static output for GitHub Pages; 606mag.com is configured as the custom domain at launch.
export default defineConfig({
  site: 'https://606mag.com',
  output: 'static',
  trailingSlash: 'always',
  build: { format: 'directory' },
});
