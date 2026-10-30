function maskSecretField(element) {
  const state = (globalThis.__browserrig ||= {});
  state.secretFields ||= new WeakSet();
  // Screenshots show discs instead of the typed characters.
  element.style.setProperty('-webkit-text-security', 'disc', 'important');
  if (state.secretFields.has(element)) {
    return;
  }
  state.secretFields.add(element);
  // Secrets must not leave the field through the clipboard or drag and drop.
  const block = (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  for (const type of ['copy', 'cut', 'dragstart']) {
    element.addEventListener(type, block, true);
  }
}

function holdsFocus(node) {
  let current = node;
  for (;;) {
    const root = current.getRootNode();
    if (root.activeElement !== current) {
      return false;
    }
    if (root.nodeType === Node.DOCUMENT_NODE) {
      return true;
    }
    current = root.host;
  }
}

function isTextField(element) {
  if (!element || element.nodeType !== Node.ELEMENT_NODE) {
    return false;
  }
  if (element.isContentEditable || element.localName === 'textarea') {
    return true;
  }
  const buttons = ['button', 'checkbox', 'color', 'file', 'hidden', 'image', 'radio', 'range'];
  return element.localName === 'input' && ![...buttons, 'reset', 'submit'].includes(element.type);
}

function focusStep(active) {
  if (active?.shadowRoot?.activeElement) {
    return {next: active.shadowRoot.activeElement};
  }
  if (!active || !['iframe', 'frame', 'object', 'embed'].includes(active.localName)) {
    return {next: null};
  }
  let inner;
  try {
    inner = active.contentDocument;
  } catch {
    return {next: null, crossOrigin: true};
  }
  if (!inner) {
    return {next: null, crossOrigin: true};
  }
  return {next: inner.activeElement, origin: inner.location?.origin ?? 'null'};
}
