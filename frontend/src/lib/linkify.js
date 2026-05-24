// Split free text into plain-text and URL segments for safe linkification.
//
// A token is treated as a URL only when it has an explicit http(s):// scheme
// AND a host containing a dot — so `http://intra/wiki` and `http://localhost`
// stay plain, while `https://example.com/x` and `https://www.example.com`
// link. No bare/scheme-less domains, so false positives are near zero and we
// need no TLD allowlist to maintain.
//
// Returns an array of segments, in order:
//   { type: 'text', value }        — render as auto-escaped text
//   { type: 'url',  value, href }  — render as <a href={href}>{value}</a>
//
// The caller renders these in Svelte (text nodes are auto-escaped, urls become
// <a>), so there is no {@html} and no injection surface.

// http(s):// + host that contains a dot (everything up to the first / or space)
// + optional path / query / fragment. The `[^\s/]*\.[^\s/]+` host segment is
// what enforces "dotted host required": there must be a dot before any slash.
const URL_RE = /https?:\/\/[^\s/]*\.[^\s/]+(?:[/?#]\S*)?/gi;

// Sentence punctuation that commonly trails a URL in prose ("see https://x.com.")
// and should not be part of the link. Trimmed back into the following text.
const TRAILING_PUNCT_RE = /[.,;:!?)\]}'"]+$/;

// How many characters of the path/query to show after the (always-full) host.
const URL_DISPLAY_TAIL = 8;

// Compact display text for a URL: drop the scheme, always show the full host,
// then up to URL_DISPLAY_TAIL more characters of the path/query, with an
// ellipsis only when there's more. The full URL stays in href/title. e.g.
//   https://example.com/files/rev-B/x.pdf  ->  example.com/files/r…
//   https://example.com/x                  ->  example.com/x   (≤ 8, no ellipsis)
//   https://example.com                    ->  example.com     (nothing after host)
export function truncateUrl(url) {
  const afterScheme = url.replace(/^https?:\/\//i, '');
  const sep = afterScheme.search(/[/?#]/);
  if (sep === -1) return afterScheme; // host only — nothing to truncate
  const host = afterScheme.slice(0, sep);
  const remainder = afterScheme.slice(sep);
  if (remainder.length <= URL_DISPLAY_TAIL) return afterScheme;
  return host + remainder.slice(0, URL_DISPLAY_TAIL) + '…';
}

export function linkify(text) {
  const segments = [];
  if (!text) return segments;

  let lastIndex = 0;
  URL_RE.lastIndex = 0;
  let match;
  while ((match = URL_RE.exec(text)) !== null) {
    const start = match.index;
    const full = match[0];
    const punct = (full.match(TRAILING_PUNCT_RE) || [''])[0];
    const url = punct ? full.slice(0, -punct.length) : full;

    // Defensive: a degenerate match that trims to nothing — skip it.
    if (!url) {
      URL_RE.lastIndex = start + full.length;
      continue;
    }

    if (start > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, start) });
    }
    segments.push({ type: 'url', value: url, href: url, display: truncateUrl(url) });

    // Leave any trimmed trailing punctuation to be emitted as text, but advance
    // the regex past the whole match so it isn't rescanned.
    lastIndex = start + url.length;
    URL_RE.lastIndex = start + full.length;
  }

  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) });
  }
  return segments;
}
