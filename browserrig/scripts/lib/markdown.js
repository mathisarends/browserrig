function truncateMarkdown(markdown, maxChars) {
  if (markdown.length <= maxChars) {
    return markdown;
  }
  const prefix = markdown.slice(0, maxChars);
  let offset = 0;
  let open = null;
  for (const line of prefix.split('\n')) {
    const marker = line.match(/^(`{3,}|~{3,})(.*)$/);
    if (marker) {
      open = updateFence(open, marker, offset, line.length);
    }
    offset += line.length + 1;
  }
  if (!open) {
    return prefix;
  }
  const closing = '\n' + open.marker;
  const end = maxChars - closing.length;
  return end >= open.end ? prefix.slice(0, end) + closing : prefix.slice(0, open.start);
}

function updateFence(open, match, offset, length) {
  if (!open) {
    return {marker: match[1], start: offset, end: offset + length};
  }
  const closes =
    match[1][0] === open.marker[0] &&
    match[1].length >= open.marker.length &&
    !match[2].trim();
  return closes ? null : open;
}
