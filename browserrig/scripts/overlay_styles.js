function browserrigOverlayStyles(_args) {
  // Trusted surface CSS uses CSSOM, so the inspected page's inline-style CSP
  // remains unchanged. Each surface has its own document and style scope.
  const sheets = [...document.querySelectorAll('style')].map((node) => {
    const sheet = new CSSStyleSheet({media: node.media});
    sheet.replaceSync(node.textContent);
    node.remove();
    return sheet;
  });
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, ...sheets];
  for (const node of document.querySelectorAll('[style]')) {
    node.style.cssText = node.getAttribute('style');
  }
}
