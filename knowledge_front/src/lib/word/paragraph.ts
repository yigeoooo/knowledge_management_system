import { Extension, type Editor, type RawCommands } from '@tiptap/core'
import { Plugin } from '@tiptap/pm/state'
import type { Node } from '@tiptap/pm/model'
import type { EditorView } from '@tiptap/pm/view'

const blockTypes = ['paragraph', 'heading']
export const pixelsPerCm = 96 / 2.54

export function indentCharacters(attrs: Record<string, unknown>, fontSize = 14) {
  const scales: Record<string, number> = { em: fontSize, px: 1, pt: 96 / 72, cm: pixelsPerCm, mm: pixelsPerCm / 10, in: 96 }
  return Number(attrs.indent || 0) * 2 * (scales[String(attrs.indentUnit || 'em')] || fontSize) / fontSize
}

function bounds(editor: Editor, node: Node, pos: number) {
  let element: HTMLElement | null = null
  try { element = editor.view.nodeDOM(pos) as HTMLElement | null } catch { /* A newly split node is not rendered yet. */ }
  const style = element?.nodeType === 1 ? getComputedStyle(element) : null
  const font = parseFloat(style?.fontSize || '14')
  const root = editor.view.dom
  const rootStyle = getComputedStyle(root)
  const width = element?.clientWidth || root.clientWidth - parseFloat(rootStyle.paddingLeft) - parseFloat(rootStyle.paddingRight)
  return { font, max: Math.max(0, Math.min(8, (width - font * 2) / font)) }
}

function changeIndent(editor: Editor, delta: number): ReturnType<RawCommands['command']> {
  return ({ tr, dispatch, commands }) => {
    for (const [list, item] of [['orderedList', 'listItem'], ['bulletList', 'listItem'], ['taskList', 'taskItem']]) {
      if (editor.isActive(list!)) return delta > 0 ? commands.sinkListItem(item!) : commands.liftListItem(item!)
    }
    if (delta < 0 && editor.isActive('blockquote')) return commands.lift('blockquote')
    tr.doc.nodesBetween(tr.selection.from, tr.selection.to, (node, pos) => {
      if (!blockTypes.includes(node.type.name)) return
      const { font, max } = bounds(editor, node, pos)
      const chars = Math.max(0, Math.min(max, indentCharacters(node.attrs, font) + delta * 2))
      if (dispatch) tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: chars / 2, indentUnit: 'em',
        ...(delta < 0 && !chars ? { paragraphLeft: 0 } : {}) })
    })
    // Consume Tab even at the boundary, so focus cannot escape the document.
    return true
  }
}

export function clearParagraphIndent(editor: Editor) {
  for (const listItem of ['listItem', 'taskItem']) {
    while (editor.isActive(listItem) && editor.commands.liftListItem(listItem)) { /* Lift nested list levels. */ }
  }
  while (editor.isActive('blockquote') && editor.commands.lift('blockquote')) { /* Lift nested quotes. */ }
  editor.chain().focus().updateAttributes('paragraph', { indent: 0, indentUnit: 'em', paragraphLeft: 0, paragraphRight: 0 })
    .updateAttributes('heading', { indent: 0, indentUnit: 'em', paragraphLeft: 0, paragraphRight: 0 }).run()
}

export function paragraphKeyDown(view: EditorView, event: KeyboardEvent) {
  if (event.isComposing || event.altKey) return false
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    const commands = (view as EditorView & { __umoPageBreak?: () => boolean }).__umoPageBreak
    if (commands) {
      event.preventDefault()
      return commands()
    }
    return false
  }
  if (event.ctrlKey || event.metaKey) return false
  const { selection } = view.state
  const { $from } = selection
  if (event.key === 'Backspace' && selection.empty && $from.parentOffset === 0 && blockTypes.includes($from.parent.type.name)) {
    const attrs = $from.parent.attrs
    if (attrs.indent || attrs.paragraphLeft) {
      view.dispatch(view.state.tr.setNodeMarkup($from.before(), undefined, { ...attrs, indent: 0, indentUnit: 'em', paragraphLeft: 0 }))
      return true
    }
  }
  return false
}

export const WordParagraph = Extension.create({
  name: 'wordParagraph',
  // Umo's toolbar invokes these same commands. Override their behavior once for
  // toolbar and keyboard, without installing a second extension named "indent".
  priority: 50,
  addGlobalAttributes() {
    return [{ types: blockTypes, attributes: { lineSpacingPt: {
      default: null,
      renderHTML: (attrs: Record<string, number>) => attrs.lineSpacingPt ? { style: `line-height: ${attrs.lineSpacingPt}pt` } : {},
    }, pageBreakBefore: {
      default: false,
      renderHTML: (attrs: Record<string, boolean>) => attrs.pageBreakBefore ? { style: 'break-before: page' } : {},
    }, ...Object.fromEntries(['Left', 'Right'].map(side => [`paragraph${side}`, {
      default: 0,
      parseHTML: (element: HTMLElement) => parseFloat(element.dataset[`paragraph${side}`] || '0'),
      renderHTML: (attrs: Record<string, number>) => ({ [`data-paragraph-${side.toLowerCase()}`]: attrs[`paragraph${side}`],
        style: `margin-${side.toLowerCase()}: ${attrs[`paragraph${side}`] || 0}cm` }),
    }])) } }]
  },
  addCommands() {
    return { setIndent: () => changeIndent(this.editor, 1), setOutdent: () => changeIndent(this.editor, -1) } as Partial<RawCommands>
  },
  addProseMirrorPlugins() {
    const editor = this.editor
    return [new Plugin({
      appendTransaction(transactions, _old, state) {
        if (!transactions.some(transaction => transaction.docChanged || transaction.getMeta('wordLayout'))) return
        const tr = state.tr
        state.doc.descendants((node, pos) => {
          if (!blockTypes.includes(node.type.name) || !node.attrs.indent) return
          const { font, max } = bounds(editor, node, pos)
          const chars = indentCharacters(node.attrs, font)
          if (chars > max) tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: Math.floor(max * 100) / 200, indentUnit: 'em' })
        })
        return tr.docChanged ? tr : undefined
      },
    })]
  },
})
