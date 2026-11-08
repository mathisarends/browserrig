/* global resolveElement */
function browserrigFileInput({count}) {
  const target = resolveElement(this);
  const input = resolveElement(target.localName === 'label' ? target.control : target);
  if (input.localName !== 'input' || input.type !== 'file') {
    throw new Error('NOT_FILE_INPUT');
  }
  if (count > 1 && !input.multiple) {
    throw new Error('FILE_INPUT_NOT_MULTIPLE');
  }
  return input;
}
