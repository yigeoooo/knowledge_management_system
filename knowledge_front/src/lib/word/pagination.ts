import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet, type EditorView } from '@tiptap/pm/view'

export interface PaperLayout {
  width: number
  height: number
  left: number
  right: number
  top: number
  bottom: number
  enabled: boolean
}
const pageGap = 24
const key = new PluginKey<number>('wordPagination')

// Pagination is presentation only: floats reserve the bottom margin, sheet gap,
// and next top margin inside the text flow, including inside long paragraphs.
// They never become document nodes, saved text, undo steps, or DOCX page breaks.
export function wordPagination(layout: () => PaperLayout) {
  return Extension.create({
    name: 'wordPagination',
    addProseMirrorPlugins() {
      return [new Plugin<number>({
        key,
        state: { init: () => 1, apply: (tr, count) => tr.getMeta(key) ?? count },
        props: {
          decorations(state) {
            const paper = layout()
            if (!paper.enabled) return DecorationSet.empty
            const count = key.getState(state) || 1
            return DecorationSet.create(state.doc, [Decoration.widget(0, () => {
              const wrapper = document.createElement('div')
              wrapper.className = 'word-pagination-floats'
              wrapper.setAttribute('aria-hidden', 'true')
              wrapper.contentEditable = 'false'
              for (let index = 1; index < count; index++) {
                const spacer = document.createElement('div')
                spacer.className = 'word-page-spacer'
                spacer.style.marginTop = `${paper.height - paper.top - paper.bottom}px`
                const gap = document.createElement('div')
                gap.className = 'word-page-gap'
                gap.style.height = `${paper.bottom + pageGap + paper.top}px`
                gap.style.background = `linear-gradient(to bottom, white ${paper.bottom}px, #f4f5f7 ${paper.bottom}px, #f4f5f7 ${paper.bottom + pageGap}px, white ${paper.bottom + pageGap}px)`
                wrapper.append(spacer, gap)
              }
              return wrapper
            }, { side: -1, key: JSON.stringify([count, paper]) })])
          },
        },
        view(view) {
          let frame = 0
          let destroyed = false
          let needsScroll = false
          let measuredLayout = ''
          const schedule = () => { if (!frame && !destroyed) frame = requestAnimationFrame(measure) }
          const measure = () => {
            frame = 0
            if (destroyed || view.composing) return
            const paper = layout()
            const root = view.dom
            const sheet = root.closest<HTMLElement>('.umo-page-content')
            if (!sheet) return
            const signature = JSON.stringify(paper)
            const changed = signature !== measuredLayout
            measuredLayout = signature
            root.classList.toggle('word-paginated', paper.enabled)
            root.style.setProperty('--word-page-left', `${paper.left}px`)
            root.style.setProperty('--word-page-right', `${paper.right}px`)
            root.style.paddingTop = `${paper.top}px`
            root.style.paddingBottom = `${paper.bottom}px`
            const box = root.getBoundingClientRect()
            const scale = box.width / root.offsetWidth || 1
            let adjustedBreak = false
            // A user-inserted hard page break still remains a real document node.
            // Its screen height fills the rest of this page and the next margin.
            view.state.doc.descendants((node, pos) => {
              if (node.type.name !== 'pageBreak') return
              const element = view.nodeDOM(pos)
              if (!(element instanceof HTMLElement)) return
              const y = (element.getBoundingClientRect().top - box.top) / scale
              const next = (Math.floor((y - paper.top + 0.5) / (paper.height + pageGap)) + 1) * (paper.height + pageGap) + paper.top
              const height = paper.enabled ? Math.max(1, next - y) : 1
              if (Math.abs(parseFloat(element.style.height || '1') - height) > 0.5) {
                element.style.height = `${height}px`
                adjustedBreak = true
              }
            })
            const current = key.getState(view.state) || 1
            let bottom = paper.top
            // Use actual document nodes; Umo appends cursor/insert decorations
            // after them, which must not be mistaken for the end of the text.
            view.state.doc.forEach((node, pos) => {
              const element = view.nodeDOM(pos)
              if (element instanceof HTMLElement) bottom = Math.max(bottom, (element.getBoundingClientRect().bottom - box.top) / scale)
            })
            const count = paper.enabled ? Math.max(1, Math.ceil((bottom + paper.bottom + pageGap - 1) / (paper.height + pageGap))) : 1
            root.style.minHeight = paper.enabled ? `${count * paper.height + (count - 1) * pageGap}px` : ''
            sheet.dataset.pageCount = String(count)
            if (count !== current || changed || adjustedBreak) {
              view.dispatch(view.state.tr.setMeta(key, count).setMeta('addToHistory', false))
              schedule()
            } else if (needsScroll) {
              needsScroll = false
              view.dispatch(view.state.tr.scrollIntoView().setMeta('addToHistory', false))
            }
          }
          const observer = new ResizeObserver(schedule)
          observer.observe(view.dom)
          const fontsReady = () => schedule()
          document.fonts.addEventListener('loadingdone', fontsReady)
          schedule()
          return {
            update(next: EditorView, previous) {
              if (!next.state.doc.eq(previous.doc)) needsScroll = true
              schedule()
            },
            destroy() { destroyed = true; cancelAnimationFrame(frame); observer.disconnect(); document.fonts.removeEventListener('loadingdone', fontsReady) },
          }
        },
      })]
    },
  })
}
