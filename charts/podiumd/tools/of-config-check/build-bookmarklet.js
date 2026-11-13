// Rebuild form-config-check.bookmarklet.txt from form-config-check.js, minified
// with terser: npm run build
const fs = require("fs");
const path = require("path");
const { minify } = require("terser");

const SOURCE = path.join(__dirname, "form-config-check.js");
const TARGET = path.join(__dirname, "form-config-check.bookmarklet.txt");

async function buildBookmarklet() {
  const { code } = await minify(fs.readFileSync(SOURCE, "utf8"), {
    compress: { passes: 2 },
    mangle: true,
    format: { comments: false },
  });
  return `javascript:${encodeURIComponent(code)}\n`;
}

if (require.main === module) {
  buildBookmarklet().then((bookmarklet) => {
    fs.writeFileSync(TARGET, bookmarklet);
    console.log(`form-config-check.bookmarklet.txt: ${bookmarklet.length} characters`);
  });
}
module.exports = { buildBookmarklet, TARGET };
