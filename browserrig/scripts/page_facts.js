function browserrigPageFacts(_args) {
  return {
    url: location.href,
    title: document.title,
    width: innerWidth,
    height: innerHeight,
    scroll_y: scrollY,
  };
}
