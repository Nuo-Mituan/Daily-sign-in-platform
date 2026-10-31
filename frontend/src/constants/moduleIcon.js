// Single source of truth for local module icon formats.
export const ICON_EXTENSIONS = Object.freeze([
  'ico', 'png', 'jpg', 'jpeg', 'webp',
])
export const ICON_EXT_RE = new RegExp(
  `\\.(${ICON_EXTENSIONS.map((ext) => (ext === 'jpg' ? 'jpe?g' : ext)).join('|')})$`,
  'i',
)

export function isSupportedIconExtension(value = '') {
  return ICON_EXT_RE.test(value)
}

/** True for path-like input; does NOT imply the extension is supported. */
export function looksLikeLocalPath(value = '') {
  return /[\\/]/.test(value) || isSupportedIconExtension(value)
}
