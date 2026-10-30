/* global planScroll, resolveElement */
function browserrigScroll({clip = null}) {
  const el = resolveElement(this);
  return planScroll(el, {clip});
}
