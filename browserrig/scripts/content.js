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
  ]);
  let visited = 0;
  let textLength = 0;
  let truncated = false;
  let frames = 0;
  const literals = [];
  const page = location.href.split('#')[0];
  let lastHref = '';

  function escape(text) {
    return text.replace(/([\\`*_[\]<>#|])/g, '\\$1');
  }

  function text(value, pre) {
    const remaining = Math.max(0, maxChars - textLength);
    if (value.length > remaining) {
      truncated = true;
    }
    const part = value.slice(0, remaining).replace(/\0/g, '');
    textLength += part.length;
    return pre ? part : escape(part.replace(/\s+/g, ' '));
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
    return node.hidden || node.getAttribute('aria-hidden') === 'true' || !canTraverse(node);
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
      const href = url.origin === origin ? url.pathname + url.search + url.hash : url.href;
      return href.replace(/[<>\s()]/g, (char) => encodeURIComponent(char));
    } catch {
      return '';
    }
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
      const marker = node.localName === 'ol' ? `${number++}. ` : '- ';
      const value = render(child, depth + 1).trim();
      if (value) {
        items.push(marker + value.replace(/\n/g, '\n' + ' '.repeat(marker.length)));
      }
    }
    return '\n\n' + items.join('\n') + '\n\n';
  }

  function table(node, depth) {
    const rows = Array.from(node.rows)
      .filter((row) => !hidden(row))
      .map((row) => tableRow(row, depth + 1))
      .filter((row) => row.some(Boolean));
    if (!rows.length) {
      return '';
    }
    const width = Math.max(...rows.map((row) => row.length));
    if (!node.rows[0]?.querySelector('th')) {
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

  function tableRow(row, depth) {
    return Array.from(row.cells).map((cell) =>
      render(cell, depth + 1)
        .trim()
        .replace(/\n+/g, '<br>'),
    );
  }

  function format(node, value) {
    const tag = node.localName;
    if (/^h[1-6]$/.test(tag)) {
      return '\n\n' + '#'.repeat(Number(tag[1])) + ' ' + value.trim() + '\n\n';
    }
    if (tag === 'a') {
      const href = node.hasAttribute('href') ? destination(node.getAttribute('href')) : '';
      if (!href || !value.trim()) {
        return value;
      }
      // An image link and its caption link often repeat the same destination.
      if (href === lastHref) {
        return value.trim();
      }
      lastHref = href;
      return `[${value.trim()}](<${href}>)`;
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
      return '';
    }
    if (node.nodeType === Node.TEXT_NODE) {
      return isRendered(parentFor(node), true) ? text(node.textContent, pre) : '';
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return '';
    }
    if (skipped.has(node.localName) || hidden(node)) {
      return '';
    }
    return isRendered(node, true) ? element(node, depth, pre) : content(node, depth, pre);
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
    if (tag === 'table') {
      return table(node, depth);
    }
    if (tag === 'pre') {
      const value = content(node, depth, true).replace(/\n$/, '');
      const fence = fenced(value);
      return '\n\n' + literal(`${fence}\n${value}\n${fence}`) + '\n\n';
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
      const summary = Array.from(node.children).find((child) => child.localName === 'summary');
      return summary ? render(summary, depth + 1, pre) : '';
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
    const total = ((document.body || document.documentElement).innerText || '').trim().length;
    return best && bestLength >= Math.max(200, total * 0.2) ? best : null;
  }

  const main = mainRegion();
  const markdown = render(main || document.body || document.documentElement, 0)
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
    frames,
    main: main !== null,
  };
}
