function browserrigSnapshot({token, maxElements, maxText}) {
  const nodes = [];
  const roots = [document];
  const seen = new Set();
  const clean = (s, n = 300) =>
    String(s || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, n);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return (
      r.width > 0 &&
      r.height > 0 &&
      r.bottom > 0 &&
      r.right > 0 &&
      r.top < innerHeight &&
      r.left < innerWidth &&
      s.visibility !== 'hidden' &&
      s.display !== 'none' &&
      s.opacity !== '0' &&
      !el.closest('[inert]')
    );
  };
  const elements = [];
  function roleFor(el, type) {
    const explicit = el.getAttribute('role');
    if (explicit) {
      return explicit;
    }
    if (el.localName === 'input') {
      return (
        {checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button'}[type] ||
        'textbox'
      );
    }
    return (
      {a: 'link', button: 'button', textarea: 'textbox', select: 'combobox', summary: 'button'}[
        el.localName
      ] || el.localName
    );
  }

  function valueFor(el, type) {
    if (type === 'password' || !('value' in el)) {
      return null;
    }
    return clean(el.value, 500);
  }

  function collect(el) {
    if (el.shadowRoot) {
      roots.push(el.shadowRoot);
    }
    if (seen.has(el)) {
      return;
    }
    seen.add(el);
    const tag = el.localName;
    const interactive = el.matches(
      'a[href],button,input,textarea,select,summary,[draggable="true"],[role="button"],[role="link"],[role="textbox"],[role="combobox"],[role="checkbox"],[contenteditable="true"],[tabindex]',
    );
    if (!interactive || !visible(el) || elements.length >= maxElements) {
      return;
    }
    const labelled = (el.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .map((id) => clean(el.getRootNode().getElementById?.(id)?.textContent))
      .join(' ')
      .trim();
    const name = clean(
      el.getAttribute('aria-label') ||
        labelled ||
        Array.from(el.labels || [])
          .map((x) => x.textContent)
          .join(' ') ||
        el.getAttribute('alt') ||
        el.getAttribute('placeholder') ||
        el.innerText ||
        el.title,
    );
    const type = el.getAttribute('type') || '';
    const role = roleFor(el, type);
    const index = nodes.push(el) - 1;
    elements.push({
      index,
      role,
      name,
      tag,
      input_type: type,
      value: valueFor(el, type),
      disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      draggable: el.draggable,
      options: tag === 'select' ? Array.from(el.options).map((o) => clean(o.text)) : [],
    });
  }

  while (roots.length) {
    const root = roots.shift();
    for (const el of root.querySelectorAll('*')) {
      collect(el);
    }
  }
  globalThis.__browserrigElements = {token, nodes};
  return {
    url: location.href,
    title: document.title,
    width: innerWidth,
    height: innerHeight,
    scroll_y: scrollY,
    text: clean(document.body?.innerText, maxText),
    elements,
  };
}
