// text-breakpoints.mjs — make phone/tablet layouts follow the Text size too.
//
// A @media(max-width:Npx) block only knows the window width. With larger text
// (the Text setting, 2026-11) a laptop window holds as few words per line as a
// phone does, so the narrow layout is the right one. display-prefs.js puts a
// class html.bb-wN on the page whenever the window, measured in text widths,
// is at most N px at the default 18px text (html.bb-hN: the same for height). This build step copies each pure
// max-width block once more under that class, so either condition applies it.

function prefixSelectors(sel, cls) {
  return sel.split(',').map(s => s.trim()).filter(Boolean)
    .map(s => (/^(html|:root)\b/.test(s) ? s.replace(/^(html|:root)/, `html.${cls}`) : `html.${cls} ${s}`))
    .join(',')
}

function prefixRules(body, cls) {
  let out = '', i = 0
  while (i < body.length) {
    const open = body.indexOf('{', i)
    if (open < 0) break
    let depth = 1, j = open + 1
    while (j < body.length && depth) { if (body[j] === '{') depth++; else if (body[j] === '}') depth--; j++ }
    const sel = body.slice(i, open).replace(/\/\*[\s\S]*?\*\//g, '').trim()
    const decl = body.slice(open + 1, j - 1)
    if (sel && !sel.startsWith('@')) out += `${prefixSelectors(sel, cls)}{${decl}}\n`
    i = j
  }
  return out
}

export function addTextBreakpoints(css) {
  let extra = ''
  const re = /@media\s*\(\s*max-(width|height)\s*:\s*(\d+)px\s*\)\s*\{/g
  let m
  while ((m = re.exec(css))) {
    let depth = 1, j = re.lastIndex
    while (j < css.length && depth) { if (css[j] === '{') depth++; else if (css[j] === '}') depth--; j++ }
    extra += prefixRules(css.slice(re.lastIndex, j - 1), `bb-${m[1] === 'width' ? 'w' : 'h'}${m[2]}`)
  }
  return extra ? `${css}\n/* Same layouts when the Text size makes the window narrow in text widths. */\n${extra}` : css
}

export const textBreakpointsPlugin = {
  name: 'text-breakpoints',
  setup(build) {
    build.onLoad({ filter: /\.css$/ }, async (args) => {
      const { readFile } = await import('node:fs/promises')
      if (args.path.includes('node_modules') || args.path.endsWith('fonts.css')) return undefined
      return { contents: addTextBreakpoints(await readFile(args.path, 'utf8')), loader: 'css' }
    })
  },
}
