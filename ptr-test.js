const ptr = require('/app/node_modules/next/dist/compiled/path-to-regexp/index.js');
const toPath = ptr.compile('http://api:8000/api/:path*');
const cases = [
  ['v1', 'organizations', 'provider-call-logs-url'],
  ['v1', 'organizations', 'campaign-defaults'],
  ['v1', 'organizations', 'telephony-config'],
];
for (const p of cases) {
  try {
    console.log(JSON.stringify(p), '=>', toPath({ path: p }));
  } catch (e) {
    console.log(JSON.stringify(p), '=> ERROR', e.message);
  }
}
