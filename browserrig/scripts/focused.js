function browserrigFocused(_args) {
  let active = document.activeElement;
  while (active) {
    const inner =
      active.shadowRoot?.activeElement ??
      (active.contentDocument ? active.contentDocument.activeElement : null);
    if (!inner || inner === active) {
      break;
    }
    active = inner;
  }
  return active && active !== document.body && active !== document.documentElement
    ? active
    : null;
}
