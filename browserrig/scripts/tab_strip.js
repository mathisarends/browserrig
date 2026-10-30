function browserrigTabStrip() {
  // Pick the declared icon closest to tab-strip size; scalable icons fit any size.
  const target = 32;
  const score = (link) => {
    if (link.type === 'image/svg+xml' || /\bany\b/i.test(link.getAttribute('sizes') ?? '')) {
      return 0;
    }
    const sizes = (link.getAttribute('sizes') ?? '').match(/\d+/g);
    if (!sizes) {
      return target / 2;
    }
    return Math.min(...sizes.map((size) => Math.abs(Number(size) - target)));
  };
  const title = document.title.trim();
  if (location.protocol !== 'http:' && location.protocol !== 'https:') {
    return {title, icon: ''};
  }
  // Inline data: icons are common in SPAs; the harness decodes them without a fetch.
  const links = [...document.querySelectorAll('link[rel~="icon" i]')].filter((link) =>
    /^(?:https?|data):/.test(link.href),
  );
  links.sort((a, b) => score(a) - score(b));
  return {title, icon: links[0]?.href ?? new URL('/favicon.ico', location.origin).href};
}
