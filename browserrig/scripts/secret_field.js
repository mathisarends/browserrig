/* global holdsFocus, maskSecretField */
function browserrigSecretField(args) {
  if (args.mask) {
    maskSecretField(this);
  }
  return {origin: location.origin, focused: holdsFocus(this)};
}
