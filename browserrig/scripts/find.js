/* global parentFor, closedRootsForDocument, childrenFor */
function browserrigFind({queries, session, active, start, count, reveal, clip, close}) {
  const state = (globalThis.__browserrig ||= {});
  if (close) {
    // The find bar closes: drop the cached page text.
    state.findIndex = null;
    return {total: 0, counts: [], items: [], marks: [], scrolled: false};
  }
  const closedRoots = closedRootsForDocument();
  const skipped = new Set([
    'script',
    'style',
    'noscript',
    'template',
    'head',
    'input',
    'textarea',
    'select',
    'svg',
    'canvas',
    'iframe',
  ]);
  // Ranges kept for marks and the returned window; the total is counted beyond it.
  const maxRanges = 1000;
  const maxMarks = 300;
  const maxDepth = 400;
  const contextChars = 70;
  // Rendered text with collapsed whitespace; '\n' separates blocks so matches stay in one block.
  const text = {chars: [], nodes: [], offsets: [], hidden: [], headings: []};
  const styles = new Map();

  function style(el) {
    if (!styles.has(el)) {
      styles.set(el, getComputedStyle(el));
    }
    return styles.get(el);
  }

  function push(char, node, offset, collapsed) {
    text.chars.push(char);
    text.nodes.push(node);
    text.offsets.push(offset);
    text.hidden.push(collapsed);
  }

  function separate(block) {
    const last = text.chars.length - 1;
    if (last < 0 || text.chars[last] === '\n') {
      return;
    }
    if (!block) {
      push(' ', null, 0, false);
    } else if (text.chars[last] === ' ') {
      text.chars[last] = '\n';
    } else {
      push('\n', null, 0, false);
    }
  }

  function addText(node, collapsed) {
    const parent = node.parentElement;
    if (!collapsed && parent && style(parent).visibility !== 'visible') {
      return;
    }
    let offset = 0;
    for (const char of node.data) {
      if (!/\s/.test(char)) {
        push(char, node, offset, collapsed);
      } else if (text.chars.length && !/\s/.test(text.chars[text.chars.length - 1])) {
        push(' ', node, offset, collapsed);
      }
      offset += char.length;
    }
  }

  function revealable(el) {
    return el.getAttribute('hidden') === 'until-found';
  }

  function shown(el) {
    return el.checkVisibility() || style(el).display === 'contents';
  }

  function inline(el) {
    const display = style(el).display;
    return display.startsWith('inline') || display === 'contents' || display === 'ruby';
  }

  function visit(node, collapsed, depth) {
    for (const child of childrenFor(node, closedRoots)) {
      if (child.nodeType === Node.TEXT_NODE) {
        addText(child, collapsed);
      } else if (child.nodeType === Node.ELEMENT_NODE && depth < maxDepth) {
        visitElement(child, collapsed, depth + 1);
      }
    }
  }

  function visitDetails(details, depth) {
    // A closed <details> shows only its summary; the rest is found and opened on demand.
    const summary = [...details.children].find(
      (child) => child.localName === 'summary',
    );
    for (const child of details.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        addText(child, true);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        visitElement(child, child !== summary, depth + 1);
      }
    }
  }

  function visitElement(el, collapsed, depth) {
    if (skipped.has(el.localName) || el.getAttribute('aria-hidden') === 'true') {
      return;
    }
    if (el.localName === 'br') {
      separate(false);
      return;
    }
    const folded = collapsed || revealable(el);
    if (!folded && !shown(el)) {
      return;
    }
    const block = !inline(el);
    separate(block);
    const headingStart =
      /^h[1-6]$/.test(el.localName) || el.role === 'heading' ? text.chars.length : -1;
    if (el.localName === 'details' && !el.open && !folded) {
      visitDetails(el, depth);
    } else {
      visit(el, folded, depth);
    }
    if (headingStart >= 0) {
      const title = text.chars.slice(headingStart).join('').replace(/\s+/g, ' ').trim();
      text.headings.push({at: headingStart, text: title.slice(0, 100)});
    }
    separate(block);
  }

  function fold(char) {
    const code = char.charCodeAt(0);
    if (code < 128) {
      return code >= 65 && code <= 90 ? String.fromCharCode(code + 32) : char;
    }
    return char.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
  }

  function build() {
    visit(document, false, 0);
    // Case- and accent-insensitive like a browser's find bar; each folded unit maps back.
    const units = [];
    const unitChar = [];
    text.chars.forEach((char, index) => {
      for (const unit of fold(char)) {
        units.push(unit);
        unitChar.push(index);
      }
    });
    const haystack = units.join('');
    return {session, mutation, ...text, unitChar, haystack};
  }

  // Typing reruns the search once per key; reuse the text while the document is unchanged.
  const mutation = state.stability?.last ?? -1;
  const cached = state.findIndex;
  const index =
    cached &&
    session &&
    cached.session === session &&
    mutation >= 0 &&
    cached.mutation === mutation
      ? cached
      : build();
  state.findIndex = index;
  const {chars, nodes, offsets, hidden, headings, unitChar, haystack} = index;
  const needles = queries.map((query) =>
    [...query.replace(/\s+/g, ' ').trim()].map(fold).join(''),
  );

  function rangeFor(first, last) {
    const range = document.createRange();
    try {
      range.setStart(nodes[first], offsets[first]);
      range.setEnd(nodes[last], offsets[last] + chars[last].length);
    } catch {
      return null;
    }
    // Ends in different shadow trees collapse the range.
    return range.collapsed ? null : range;
  }

  function occurrences(needle, which) {
    const found = [];
    let at = needle ? haystack.indexOf(needle) : -1;
    while (at >= 0) {
      found.push({at, end: at + needle.length, which});
      at = haystack.indexOf(needle, at + needle.length);
    }
    return found;
  }

  // All alternatives in page order; of overlapping ones the earlier, then longer, wins.
  const hits = needles
    .flatMap(occurrences)
    .sort((a, b) => a.at - b.at || b.end - a.end);
  const counts = needles.map(() => 0);
  const matches = [];
  let reached = 0;
  for (const hit of hits) {
    if (hit.at < reached) {
      continue;
    }
    reached = hit.end;
    counts[hit.which] += 1;
    if (matches.length < maxRanges) {
      const first = unitChar[hit.at];
      const last = unitChar[hit.end - 1];
      matches.push({first, last, range: rangeFor(first, last)});
    }
  }
  const total = counts.reduce((sum, found) => sum + found, 0);

  const viewport = {
    x: clip ? clip.x : 0,
    y: clip ? clip.y : 0,
    width: clip ? clip.width : innerWidth,
    height: clip ? clip.height : innerHeight,
  };

  function folded(node) {
    // Inside a closed <details> (outside its summary) or a hidden=until-found section.
    for (let child = node, el = parentFor(node); el; child = el, el = parentFor(el)) {
      if (el.localName === 'details' && !el.open && child.localName !== 'summary') {
        return true;
      }
      if (el.nodeType === Node.ELEMENT_NODE && revealable(el)) {
        return true;
      }
    }
    return false;
  }

  function collapsedMatch(match) {
    return (
      hidden[match.first] && Boolean(match.range) && folded(match.range.startContainer)
    );
  }

  function rectsOf(match) {
    const range = match.range;
    // Collapsed content may still report stale boxes; it is not on screen.
    if (!range || collapsedMatch(match)) {
      return [];
    }
    return [...range.getClientRects()]
      .filter((rect) => rect.width > 0 && rect.height > 0)
      .map((rect) =>
        [rect.x, rect.y, rect.width, rect.height].map((v) => Math.round(v * 10) / 10),
      );
  }

  function inView([x, y, width, height]) {
    return (
      x < viewport.x + viewport.width &&
      x + width > viewport.x &&
      y < viewport.y + viewport.height &&
      y + height > viewport.y
    );
  }

  function open(node) {
    for (let el = parentFor(node); el; el = parentFor(el)) {
      if (el.localName === 'details' && !el.open) {
        el.open = true;
      }
      if (el.nodeType === Node.ELEMENT_NODE && revealable(el)) {
        el.dispatchEvent(new Event('beforematch', {bubbles: true}));
        el.removeAttribute('hidden');
      }
    }
  }

  function comfortable(box) {
    const margin = viewport.height * 0.1;
    return (
      box.width > 0 &&
      box.top >= viewport.y + margin &&
      box.bottom <= viewport.y + viewport.height - margin &&
      box.left >= viewport.x &&
      box.right <= viewport.x + viewport.width
    );
  }

  function bringIntoView(range) {
    const before = range.getBoundingClientRect();
    if (comfortable(before)) {
      return false;
    }
    range.startContainer.parentElement?.scrollIntoView({
      block: 'center',
      inline: 'nearest',
      behavior: 'instant',
    });
    const box = range.getBoundingClientRect();
    if (!comfortable(box)) {
      // A long paragraph: centre the match itself, not its whole element.
      const middle = box.top + box.height / 2 - (viewport.y + viewport.height / 2);
      scrollBy({top: middle, behavior: 'instant'});
    }
    const after = range.getBoundingClientRect();
    return (
      Math.abs(after.top - before.top) > 0.5 || Math.abs(after.left - before.left) > 0.5
    );
  }

  const current = matches[active];
  let scrolled = false;
  if (current?.range && reveal) {
    if (hidden[current.first]) {
      open(current.range.startContainer);
    }
    scrolled = bringIntoView(current.range);
  }

  const marks = [];
  matches.forEach((match, index) => {
    const rects = marks.length < maxMarks ? rectsOf(match).filter(inView) : [];
    if (rects.length) {
      marks.push({index, rects});
    }
  });

  function context(from, to) {
    return chars.slice(from, to).join('').replace(/\s+/g, ' ');
  }

  // Context stays within the match's block; '…' marks where it was cut short.
  function textBefore(match) {
    let from = match.first;
    while (from > 0 && chars[from - 1] !== '\n' && match.first - from < contextChars) {
      from -= 1;
    }
    const cut = from > 0 && chars[from - 1] !== '\n';
    return (cut ? '…' : '') + context(from, match.first).trimStart();
  }

  function textAfter(match) {
    let to = match.last + 1;
    while (to < chars.length && chars[to] !== '\n' && to - match.last <= contextChars) {
      to += 1;
    }
    const cut = to < chars.length && chars[to] !== '\n';
    return context(match.last + 1, to).trimEnd() + (cut ? '…' : '');
  }

  function headingAt(position) {
    let found = '';
    for (const heading of headings) {
      if (heading.at > position) {
        break;
      }
      found = heading.text;
    }
    return found;
  }

  const items = matches.slice(start, start + count).map((match) => ({
    before: textBefore(match),
    text: context(match.first, match.last + 1),
    after: textAfter(match),
    heading: headingAt(match.first),
    collapsed: collapsedMatch(match),
  }));

  return {total, counts, items, marks, scrolled};
}
