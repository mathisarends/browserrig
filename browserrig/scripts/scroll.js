/* global planScroll, resolveElement */
function browserrigScroll({clip = null, apply = false}) {
  const el = resolveElement(this);
  return planScroll(el, {clip, apply});
}
