/* global planScroll, resolveElement */
function browserrigScroll({token, index, clip = null}) {
  const el = resolveElement({token, index});
  return planScroll(el, {clip});
}
