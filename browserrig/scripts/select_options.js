/* global resolveElement */
function browserrigSelectOptions({values, apply = false}) {
  const el = resolveElement(this);
  if (el.localName !== 'select' || !el.multiple) {
    throw new Error('NOT_A_MULTI_SELECT');
  }
  const options = Array.from(el.options);
  const wanted = new Set();
  for (const value of values) {
    const matches = options.filter(
      (option) =>
        option.value === value || option.label.replace(/\s+/g, ' ').trim() === value,
    );
    if (matches.length === 0) {
      throw new Error('OPTION_NOT_FOUND');
    }
    if (matches.length !== 1) {
      throw new Error('OPTION_AMBIGUOUS');
    }
    wanted.add(matches[0]);
  }
  // Validate the entire change before touching any selected flag or firing events.
  const changes = options.filter((option) => option.selected !== wanted.has(option));
  if (changes.some((option) => option.matches(':disabled'))) {
    throw new Error('OPTION_DISABLED');
  }
  if (apply && changes.length) {
    for (const option of options) {
      option.selected = wanted.has(option);
    }
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  const current = Array.from(el.options);
  const selected = current.filter((option) => option.selected);
  const verified =
    !apply ||
    (el.isConnected &&
      current.length === options.length &&
      current.every((option, i) => option === options[i]) &&
      current.every((option) => option.selected === wanted.has(option)));
  let reason = '';
  if (!verified) {
    reason = el.isConnected
      ? 'Page handlers changed the options or selected set during dispatch.'
      : 'The addressed select was detached during dispatch.';
  }
  return {
    selected: selected.map((option) => ({label: option.label, value: option.value})),
    verified,
    reason,
  };
}
