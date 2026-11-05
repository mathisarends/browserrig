function browserrigOverlayMessage({data}) {
  // Deliver in the owned frame's isolated world. Returning acknowledges that
  // its synchronous message handlers ran, including during rapid native input.
  window.dispatchEvent(new MessageEvent('message', {data, source: parent}));
}
