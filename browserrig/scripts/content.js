/* global parentFor, closedRootsForDocument, childrenFor, isRendered, canTraverse, truncateMarkdown */
function browserrigContent({maxChars, mainOnly, origin}) {
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
  ]);
  const blocks = new Set([
    'address',
    'article',
    'aside',
    'div',
    'dl',
    'dt',
    'dd',
    'fieldset',
    'figcaption',
    'figure',
    'footer',
    'header',
    'main',
    'nav',
    'p',
    'section',
    'summary',
  ]);
  const tableRoles = new Set(['table', 'grid', 'treegrid']);
  const ariaTableSelector = 'table, [role="table"], [role="grid"], [role="treegrid"]';
  const cellRoles = new Set(['cell', 'gridcell', 'columnheader', 'rowheader']);
  let visited = 0;
  let textLength = 0;
  let truncated = false;
  // Set when the node or depth limit, not the character budget, ended the walk.
  let limited = false;
  let frames = 0;
  const literals = [];
  const page = location.href.split('#')[0];
  let lastHref = '';
  // Inside closed <details>: loaded but collapsed text is still read.
  let collapsed = 0;
  let skipChrome = false;

  function escape(text) {
    return text.replace(/([\\`*_[\]<>#|])/g, '\\$1');
  }

  function text(value, pre) {
    // Count what is written: collapsed whitespace does not use up the budget.
    const clean = value.replace(/\0/g, '');
    const normalized = pre ? clean : clean.replace(/\s+/g, ' ');
    const remaining = Math.max(0, maxChars - textLength);
    if (normalized.length > remaining) {
      truncated = true;
    }
    const part = normalized.slice(0, remaining);
    textLength += part.length;
    return pre ? part : escape(part);
  }

  function content(node, depth, pre = false) {
    const parts = [];
    for (const child of childrenFor(node, closedRoots)) {
      if (visited >= 50000 || textLength >= maxChars) {
        truncated = true;
        break;
      }
      parts.push(render(child, depth + 1, pre));
    }
    return parts.join('');
  }

  function hidden(node) {
    return (
      (node.hidden && node.getAttribute('hidden') !== 'until-found') ||
      node.getAttribute('aria-hidden') === 'true' ||
      !canTraverse(node)
    );
  }

  function clipped(node) {
    // Collapsed menus and panels: a zero-size box that clips its overflow shows nothing.
    const style = getComputedStyle(node);
    if (style.display === 'contents') {
      return false;
    }
    const clipY = /hidden|clip/.test(style.overflowY);
    const clipX = /hidden|clip/.test(style.overflowX);
    if (!clipX && !clipY) {
      return false;
    }
    const rect = node.getBoundingClientRect();
    return (clipY && rect.height === 0) || (clipX && rect.width === 0);
  }

  const chromeSelector =
    'header, footer, nav, [role="banner"], [role="contentinfo"], [role="navigation"]';

  function isChrome(node) {
    // Site-wide header, navigation and footer; an article's own header or footer is content.
    if (!node.matches(chromeSelector)) {
      return false;
    }
    if (node.matches('header, footer')) {
      const scope = node.parentElement?.closest(
        'article, aside, main, section, [role="article"], [role="main"], [role="region"]',
      );
      if (scope) {
        return false;
      }
    }
    // A header that carries the page title is the hero, not chrome.
    return !(node.matches('header, [role="banner"]') && node.querySelector('h1'));
  }

  function destination(value) {
    try {
      const url = new URL(value, document.baseURI);
      if (!['http:', 'https:', 'mailto:', 'tel:'].includes(url.protocol)) {
        return '';
      }
      // Links into the current document lead nowhere new; same-site links need only a path.
      if (url.href.split('#')[0] === page) {
        return '';
      }
      const href =
        url.origin === origin ? url.pathname + url.search + url.hash : url.href;
      return href.replace(/[<>\s()]/g, (char) => encodeURIComponent(char));
    } catch {
      return '';
    }
  }

  function footnote(node) {
    // Markers like [12] that only jump to the page's own reference list.
    const links = Array.from(node.querySelectorAll('a[href]'));
    return (
      links.length > 0 &&
      node.textContent.trim().length <= 12 &&
      links.every(
        (link) => link.getAttribute('href').includes('#') && !destination(link.href),
      )
    );
  }

  function fenced(value) {
    const runs = value.match(/`+/g) || [];
    return '`'.repeat(Math.max(3, ...runs.map((run) => run.length + 1)));
  }

  function literal(value) {
    literals.push(value);
    return `\0${literals.length - 1}\0`;
  }

  function list(node, depth) {
    let number = Number(node.getAttribute('start')) || 1;
    const items = [];
    for (const child of childrenFor(node, closedRoots)) {
      if (visited >= 50000 || textLength >= maxChars) {
        truncated = true;
        break;
      }
      if (child.nodeType !== Node.ELEMENT_NODE || child.localName !== 'li') {
        continue;
      }
      const value = render(child, depth + 1).trim();
      if (value) {
        // Hidden or empty items do not take a number.
        const marker = node.localName === 'ol' ? `${number++}. ` : '- ';
        items.push(marker + value.replace(/\n/g, '\n' + ' '.repeat(marker.length)));
      }
    }
    return '\n\n' + items.join('\n') + '\n\n';
  }

  function table(node, depth) {
    // Spanned cells are repeated into every row and column they cover, so each row
    // reads on its own; a cell spanning the whole row is written once.
    if (node.localName === 'table' && layoutTable(node)) {
      return layout(node, depth);
    }
    const grid = [];
    let y = 0;
    const tableRows = rowsOf(node);
    for (const row of tableRows) {
      if (visited >= 50000 || textLength >= maxChars) {
        truncated = true;
        break;
      }
      if (hidden(row)) {
        continue;
      }
      grid[y] = grid[y] || [];
      let x = 0;
      for (const cell of cellsOf(row)) {
        x = place(grid, y, x, cell, {value: tableCell(cell, depth + 1)});
      }
      y++;
    }
    const width = Math.max(0, ...grid.map((row) => row.length));
    const rows = grid
      .map((row) => {
        const entries = Array.from({length: width}, (_, index) => row[index]);
        if (width > 1 && entries.every((entry) => entry === entries[0])) {
          return [entries[0]?.value || ''];
        }
        return entries.map((entry) => entry?.value || '');
      })
      .filter((row) => row.some(Boolean));
    if (!rows.length) {
      return '';
    }
    const header = tableRows[0] ? cellsOf(tableRows[0]) : [];
    if (
      !header.some((cell) => cell.localName === 'th' || role(cell) === 'columnheader')
    ) {
      rows.unshift(Array(width).fill(''));
    }
    const lines = rows.map((row) => {
      const cells = Array.from({length: width}, (_, index) => row[index] || '');
      return '| ' + cells.join(' | ') + ' |';
    });
    lines.splice(1, 0, '| ' + Array(width).fill('---').join(' | ') + ' |');
    const caption = node.caption ? render(node.caption, depth + 1).trim() + '\n\n' : '';
    return '\n\n' + caption + lines.join('\n') + '\n\n';
  }

  function place(grid, y, start, cell, entry) {
    // The cell takes the first free column and every slot its spans cover.
    let x = start;
    while (grid[y][x]) {
      x++;
    }
    const columns = span(cell, cell.colSpan, 'aria-colspan');
    const rows = span(cell, cell.rowSpan, 'aria-rowspan');
    for (let dy = 0; dy < rows; dy++) {
      grid[y + dy] = grid[y + dy] || [];
      for (let dx = 0; dx < columns; dx++) {
        grid[y + dy][x + dx] = entry;
      }
    }
    return x + columns;
  }

  function layoutTable(node) {
    // Mozilla Readability's test for tables that only position page parts.
    if (['presentation', 'none'].includes(role(node))) {
      return true;
    }
    if (node.getAttribute('summary') || node.caption?.textContent.trim()) {
      return false;
    }
    if (node.querySelector('col, colgroup, tfoot, thead, th')) {
      return false;
    }
    if (node.querySelector('table')) {
      return true;
    }
    const rows = node.rows.length;
    const columns = Math.max(
      0,
      ...Array.from(node.rows, (row) =>
        Array.from(row.cells).reduce((sum, cell) => sum + span(cell, cell.colSpan), 0),
      ),
    );
    return rows < 10 && columns <= 4 && rows * columns <= 10;
  }

  function layout(node, depth) {
    // Each row reads as a paragraph: its cells on one line, or as blocks when they hold blocks.
    const blocks = [];
    for (const row of node.rows) {
      if (visited >= 50000 || textLength >= maxChars) {
        truncated = true;
        break;
      }
      if (hidden(row)) {
        continue;
      }
      const cells = Array.from(row.cells, (cell) =>
        render(cell, depth + 1).trim(),
      ).filter(Boolean);
      if (cells.length) {
        blocks.push(
          cells.join(cells.some((cell) => cell.includes('\n')) ? '\n\n' : ' '),
        );
      }
    }
    return '\n\n' + blocks.join('\n\n') + '\n\n';
  }

  function span(cell, native, attribute) {
    const value = Number(native ?? cell.getAttribute(attribute)) || 1;
    return Math.min(Math.max(value, 1), 100);
  }

  function role(node) {
    return (node.getAttribute('role') || '').trim().toLowerCase();
  }

  function owner(node, selector) {
    return node.parentElement?.closest(selector);
  }

  function rowsOf(node) {
    if (node.localName === 'table') {
      return Array.from(node.rows);
    }
    // Grid layouts marked up with ARIA table roles read like tables.
    return Array.from(node.querySelectorAll('[role="row"]')).filter(
      (row) => owner(row, ariaTableSelector) === node,
    );
  }

  function cellsOf(row) {
    if (row.localName === 'tr') {
      return Array.from(row.cells);
    }
    return Array.from(row.querySelectorAll('[role]')).filter(
      (cell) => cellRoles.has(role(cell)) && owner(cell, '[role="row"], tr') === row,
    );
  }

  function tableCell(cell, depth) {
    return render(cell, depth).trim().replace(/\n+/g, '<br>');
  }

  function oneLine(value) {
    // Cards wrap whole blocks in a link or heading; Markdown needs their text on one line.
    const lines = value.trim().split(/\s*\n+\s*/);
    if (lines.length === 1) {
      return lines[0];
    }
    return lines
      .map((line) => line.replace(/^(?:#{1,6}|[-*>]|\d+\.) +/, ''))
      .filter(Boolean)
      .join(' · ');
  }

  function format(node, value) {
    const tag = node.localName;
    if (/^h[1-6]$/.test(tag)) {
      const title = oneLine(value);
      return title
        ? '\n\n' + '#'.repeat(Number(tag[1])) + ' ' + title + '\n\n'
        : '\n\n';
    }
    if (tag === 'a') {
      const href = node.hasAttribute('href')
        ? destination(node.getAttribute('href'))
        : '';
      if (!href || !value.trim()) {
        return value;
      }
      // An image link and its caption link often repeat the same destination; titles keep it.
      if (href === lastHref && !node.closest('h1, h2, h3, h4, h5, h6')) {
        return value.trim();
      }
      lastHref = href;
      return `[${oneLine(value)}](<${href}>)`;
    }
    if (tag === 'strong' || tag === 'b') {
      return value.trim() ? `**${value.trim()}**` : '';
    }
    if (tag === 'em' || tag === 'i') {
      return value.trim() ? `*${value.trim()}*` : '';
    }
    if (tag === 'blockquote') {
      return '\n\n' + value.trim().replace(/^/gm, '> ') + '\n\n';
    }
    if (blocks.has(tag)) {
      return '\n\n' + value.trim() + '\n\n';
    }
    return value;
  }

  function render(node, depth, pre = false) {
    if (++visited > 50000 || depth > 128) {
      truncated = true;
      limited = true;
      return '';
    }
    if (node.nodeType === Node.TEXT_NODE) {
      return collapsed || isRendered(parentFor(node), true)
        ? text(node.textContent, pre)
        : '';
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return '';
    }
    if (skipped.has(node.localName) || hidden(node)) {
      return '';
    }
    if (skipChrome && isChrome(node)) {
      return '';
    }
    if (collapsed) {
      return element(node, depth, pre);
    }
    if (clipped(node)) {
      return '';
    }
    return isRendered(node, true)
      ? element(node, depth, pre)
      : content(node, depth, pre);
  }

  function element(node, depth, pre) {
    const tag = node.localName;
    if (tag === 'iframe' || tag === 'frame') {
      frames++;
      return '';
    }
    if (tag === 'ul' || tag === 'ol') {
      return list(node, depth);
    }
    if (tag === 'table' || (tableRoles.has(role(node)) && rowsOf(node).length)) {
      return table(node, depth);
    }
    if (tag === 'pre') {
      const value = content(node, depth, true).replace(/\n$/, '');
      const fence = fenced(value);
      return '\n\n' + literal(`${fence}\n${value}\n${fence}`) + '\n\n';
    }
    if (tag === 'sup' && footnote(node)) {
      return '';
    }
    if (tag === 'code' && !pre) {
      const value = content(node, depth, true).replace(/\s+/g, ' ');
      const runs = value.match(/`+/g) || [];
      const fence = '`'.repeat(Math.max(1, ...runs.map((run) => run.length + 1)));
      return literal(`${fence} ${value} ${fence}`);
    }
    // Controls are listed by observe; only disclosure buttons inside headings name content.
    if (tag === 'button' && !node.closest('h1, h2, h3, h4, h5, h6, [role="heading"]')) {
      return '';
    }
    if (tag === 'label' && node.control) {
      return '';
    }
    if (tag === 'br') {
      return '\n';
    }
    if (tag === 'hr') {
      return '\n\n---\n\n';
    }
    if (tag === 'img') {
      return text(node.getAttribute('alt') || '', pre);
    }
    if (tag === 'details' && !node.open) {
      // FAQ answers and disclosures are loaded content; read them without opening.
      const summary = Array.from(node.children).find(
        (child) => child.localName === 'summary',
      );
      const head = summary ? oneLine(render(summary, depth + 1, pre)) : '';
      collapsed++;
      const body = Array.from(childrenFor(node, closedRoots))
        .filter((child) => child !== summary)
        .map((child) => render(child, depth + 1, pre))
        .join('');
      collapsed--;
      return '\n\n' + (head ? head + '\n\n' : '') + body.trim() + '\n\n';
    }
    const value = content(node, depth, pre);
    return pre ? value : format(node, value);
  }

  function mainRegion() {
    // The page's main landmark, unless it holds too little of the visible text to trust.
    if (!mainOnly) {
      return null;
    }
    let best = null;
    let bestLength = 0;
    for (const node of document.querySelectorAll('main, [role="main"]')) {
      const length = hidden(node) ? 0 : (node.innerText || '').trim().length;
      if (length > bestLength) {
        best = node;
        bestLength = length;
      }
    }
    const total = ((document.body || document.documentElement).innerText || '').trim()
      .length;
    if (best && bestLength >= Math.max(200, total * 0.2)) {
      return best;
    }
    // Without a usable main landmark, leave out site chrome if enough text remains.
    let chromeLength = 0;
    for (const node of document.querySelectorAll(chromeSelector)) {
      if (
        isChrome(node) &&
        !node.parentElement?.closest(chromeSelector) &&
        !hidden(node)
      ) {
        chromeLength += (node.innerText || '').trim().length;
      }
    }
    skipChrome = chromeLength > 0 && total - chromeLength >= Math.max(200, total * 0.2);
    return null;
  }

  const main = mainRegion();
  const root = main || document.body || document.documentElement;
  // The part of the viewport this read covers, for viewers that show what was read.
  const box = root.getBoundingClientRect();
  const left = Math.max(0, box.left);
  const top = Math.max(0, box.top);
  const right = Math.min(innerWidth, box.right);
  const bottom = Math.min(innerHeight, box.bottom);
  const markdown = render(root, 0)
    .replace(/(\S) {2,}/g, '$1 ')
    .replace(/[ \t]+$/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\0(\d+)\0/g, (_, index) => literals[Number(index)])
    .trim();
  return {
    url: location.href,
    title: document.title,
    markdown: truncateMarkdown(markdown, maxChars),
    truncated: truncated || markdown.length > maxChars,
    limited: limited || visited >= 50000,
    frames,
    main: main !== null,
    chrome: skipChrome,
    region:
      right > left && bottom > top
        ? {x: left, y: top, width: right - left, height: bottom - top}
        : null,
  };
}
