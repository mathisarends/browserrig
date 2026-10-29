/* global planScroll */
function browserrigOwnerScroll({clip = null, targetBounds}) {
  if (!this.isConnected) {
    throw new Error('STALE_ELEMENT');
  }
  return planScroll(this, {clip, targetBounds});
}
