function browserrigSingleTab({enabled, binding}) {
  const key = Symbol.for('browserrig.singleTab');
  if (globalThis[key]) {
    if (!enabled) {
      globalThis[key]();
    }
    return;
  }
  if (!enabled) {
    return;
  }

  const originalOpen = globalThis.open;
  const originalSubmit = HTMLFormElement.prototype.submit;
  const pending = new Set();
  const localTargets = new Set(['_self', '_parent', '_top']);

  function localTarget(target) {
    const name = String(target);
    if (!name || name.toLowerCase() === '_blank') {
      return false;
    }
    if (localTargets.has(name.toLowerCase()) || (name && name === globalThis.name)) {
      return true;
    }
    return Array.from(document.querySelectorAll('iframe[name], frame[name]')).some(
      (frame) => frame.name === name,
    );
  }

  function normalize(element, attribute, fallback = '') {
    const target = element.getAttribute(attribute) || fallback;
    if (!target || localTarget(target)) {
      return;
    }
    const previous = element.getAttribute(attribute);
    element.setAttribute(attribute, '_top');
    function restore() {
      if (element.getAttribute(attribute) === '_top') {
        if (previous === null) {
          element.removeAttribute(attribute);
        } else {
          element.setAttribute(attribute, previous);
        }
      }
      pending.delete(restore);
    }
    pending.add(restore);
    setTimeout(restore, 0);
  }

  function baseTarget() {
    return document.querySelector('base[target]')?.getAttribute('target') || '';
  }

  function click(event) {
    const link = event
      .composedPath()
      .find(
        (node) => node instanceof HTMLAnchorElement || node instanceof HTMLAreaElement,
      );
    if (link) {
      normalize(link, 'target', baseTarget());
    }
  }

  function submit(event) {
    const form = event.target;
    normalize(form, 'target', baseTarget());
    if (event.submitter) {
      normalize(event.submitter, 'formtarget');
    }
  }

  function open(url = '', target = '', features = '') {
    if (localTarget(target)) {
      return originalOpen.call(this, url, target, features);
    }
    let destination;
    try {
      destination = new URL(String(url), document.baseURI);
    } catch {
      globalThis[binding]('');
      return null;
    }
    if (!url || !['http:', 'https:'].includes(destination.protocol)) {
      globalThis[binding]('');
      return null;
    }
    try {
      globalThis.top.location.href = destination.href;
    } catch {
      globalThis[binding]('');
    }
    return null;
  }

  function programmaticSubmit() {
    normalize(this, 'target', baseTarget());
    return originalSubmit.call(this);
  }

  globalThis.open = open;
  HTMLFormElement.prototype.submit = programmaticSubmit;
  globalThis.addEventListener('click', click, true);
  globalThis.addEventListener('click', click);
  globalThis.addEventListener('submit', submit, true);
  globalThis.addEventListener('submit', submit);
  globalThis[key] = () => {
    globalThis.removeEventListener('click', click, true);
    globalThis.removeEventListener('click', click);
    globalThis.removeEventListener('submit', submit, true);
    globalThis.removeEventListener('submit', submit);
    if (globalThis.open === open) {
      globalThis.open = originalOpen;
    }
    if (HTMLFormElement.prototype.submit === programmaticSubmit) {
      HTMLFormElement.prototype.submit = originalSubmit;
    }
    for (const restore of pending) {
      restore();
    }
    delete globalThis[key];
  };
}
