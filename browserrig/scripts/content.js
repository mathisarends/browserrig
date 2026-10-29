function browserrigContent({maxChars}) {
  const closedRoots = new Map(
    (globalThis.__browserrig?.dom?.roots || []).map((root) => [root.host, root]),
  );
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

  function children(node) {
    const shadow = node.shadowRoot || closedRoots.get(node);
    if (shadow) {
      return shadow.childNodes;
    }
    if (node.localName === 'slot') {
      const assigned = node.assignedNodes({flatten: true});
      return assigned.length ? assigned : node.childNodes;
    }
    return node.childNodes;
  }

  function content(node, depth, pre = false) {
    const parts = [];
    for (const child of children(node)) {
      if (visited >= 50000 || textLength >= maxChars) {
        truncated = true;
        break;
      }
      parts.push(render(child, depth + 1, pre));
    }
    return parts.join('');
  }

  function hidden(node) {
    const style = getComputedStyle(node);
    return (
      node.hidden ||
      node.getAttribute('aria-hidden') === 'true' ||
      style.display === 'none' ||
      style.visibility === 'hidden' ||
      style.visibility === 'collapse' ||
      Number(style.opacity) === 0
    );
  }

  function destination(value) {
    try {
      const url = new URL(value, document.baseURI);
      if (!['http:', 'https:', 'mailto:', 'tel:'].includes(url.protocol)) {
        return '';
      }
      return url.href.replace(/[<>\s()]/g, (char) => encodeURIComponent(char));
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
    for (const child of children(node)) {
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
      return href && value.trim() ? `[${value.trim()}](<${href}>)` : value;
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
      return text(node.textContent, pre);
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return '';
    }
    if (skipped.has(node.localName) || hidden(node)) {
      return '';
    }
    return element(node, depth, pre);
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

  const markdown = render(document.body || document.documentElement, 0)
    .replace(/\n[ \t]+\n/g, '\n\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\0(\d+)\0/g, (_, index) => literals[Number(index)])
    .trim();
  return {
    url: location.href,
    title: document.title,
    markdown: markdown.slice(0, maxChars),
    truncated: truncated || markdown.length > maxChars,
    frames,
  };
}
