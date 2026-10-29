function ({token, maxElements, maxText}) {
  const nodes = [];
  const roots = [document];
  const seen = new Set();
  const clean = (s, n = 300) => String(s || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
      r.top < innerHeight && r.left < innerWidth && s.visibility !== 'hidden' &&
      s.display !== 'none' && s.opacity !== '0' && !el.closest('[inert]');
  };
  const elements = [];
  while (roots.length) {
    const root = roots.shift();
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) roots.push(el.shadowRoot);
      if (seen.has(el)) continue;
      seen.add(el);
      const tag = el.localName;
      const interactive = el.matches('a[href],button,input,textarea,select,summary,[role="button"],[role="link"],[role="textbox"],[role="combobox"],[role="checkbox"],[contenteditable="true"],[tabindex]');
      if (!interactive || !visible(el) || elements.length >= maxElements) continue;
      const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
        .map(id => clean(el.getRootNode().getElementById?.(id)?.textContent)).join(' ').trim();
      const name = clean(el.getAttribute('aria-label') || labelled ||
        Array.from(el.labels || []).map(x => x.textContent).join(' ') ||
        el.getAttribute('alt') || el.getAttribute('placeholder') || el.innerText || el.title);
      const type = el.getAttribute('type') || '';
      const role = el.getAttribute('role') || ({a:'link', button:'button', textarea:'textbox',
        select:'combobox', summary:'button'}[tag]) || (tag === 'input' ?
        ({checkbox:'checkbox', radio:'radio', submit:'button', button:'button'}[type] || 'textbox') : tag);
      const index = nodes.push(el) - 1;
      elements.push({index, role, name, tag, input_type: type,
        value: type === 'password' ? null : ('value' in el ? clean(el.value, 500) : null),
        disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
        options: tag === 'select' ? Array.from(el.options).map(o => clean(o.text)) : []});
    }
  }
  globalThis.__browserrigElements = {token, nodes};
  return {url: location.href, title: document.title, width: innerWidth, height: innerHeight,
    scroll_y: scrollY, text: clean(document.body?.innerText, maxText), elements};
}
