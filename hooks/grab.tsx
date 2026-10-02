/* @jsxRuntime classic */
/* @jsx h */
/* @jsxFrag Fragment */
import type { ClientModule } from 'claude-code'

/**
 * An invisible region laid over the pet that turns a press-and-drag into
 * band columns for the hooks module, which moves the pet and redraws.
 *
 * The pet's `Image` takes no pointer events and a `Client` can't draw an
 * `Image`, so the grab sits on top of the picture and draws an empty box:
 * no characters, nothing to cover the pixels.
 */

export type GrabProps = {
  /** The band column the pet's left edge is drawn at. */
  left: number
  columns: number
  rows: number
}

/** What the region posts: the pointer's band column, with the grab's phase. */
export type GrabMessage = { phase: 'down' | 'move' | 'up'; column: number }

const Grab: ClientModule<GrabProps> = (props, surface) => {
  const { Box } = surface.elements

  surface.onPointer(event => {
    if (event.type === 'enter' || event.type === 'leave') {
      return
    }
    // A hover move has no button; only a held drag counts.
    if (event.type === 'move' && event.button === undefined) {
      return
    }
    const x = event.fine?.x ?? event.x + 0.5
    const message: GrabMessage = { phase: event.type, column: props.left + x }
    surface.post(message)
  })

  return <Box width={props.columns} height={props.rows} />
}

export default Grab
