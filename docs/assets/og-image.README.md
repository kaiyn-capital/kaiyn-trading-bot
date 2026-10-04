# Static Open Graph card

`og-image.svg` is the editable source. All artwork is vector geometry; Geist Latin
is embedded under the SIL Open Font License in `og-font-OFL.txt`. The site serves
`og-image.png`, not the SVG or a dynamic image endpoint.

Edit the SVG text, coordinates or colours, then render using Node.js and an
available Playwright installation and Google Chrome:

```sh
node scripts/render_og_image.cjs
```

If Playwright is supplied by an external tooling environment, set `NODE_PATH` to
its `node_modules` directory. No website or trading runtime dependency is needed.
The renderer waits for the embedded font, checks the 1200 × 630 canvas and text
safe area, and writes the PNG only after those checks pass. Inspect the output
at full size and as a small sharing card before publishing.
