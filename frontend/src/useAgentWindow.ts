import { useEffect, useRef, useState, type PointerEvent, type KeyboardEvent } from 'react';

type Frame = { x: number; y: number; width: number; height: number };
export type ResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
type Mode = 'move' | 'resize';
const initial = (): Frame => {
  try {
    const value = JSON.parse(localStorage.getItem('sprintlens.agent.window') || 'null');
    if (
      value &&
      Object.values(value).every((v) => typeof v === 'number' && Number.isFinite(v)) &&
      ['x', 'y', 'width', 'height'].every((k) => k in value)
    )
      return clamp(value);
  } catch {
    /* use viewport defaults */
  }
  return clamp({ x: innerWidth - 564, y: innerHeight - 822, width: 540, height: 730 });
};
function clamp(f: Frame): Frame {
  const width = Math.min(Math.max(350, f.width), innerWidth - 16);
  const height = Math.min(Math.max(400, f.height), innerHeight - 24);
  return {
    width,
    height,
    x: Math.max(8, Math.min(f.x, innerWidth - width - 8)),
    y: Math.max(8, Math.min(f.y, innerHeight - height - 8)),
  };
}
function resized(f: Frame, edge: ResizeEdge, dx: number, dy: number): Frame {
  let left = f.x,
    right = f.x + f.width,
    top = f.y,
    bottom = f.y + f.height;
  const minWidth = Math.min(350, innerWidth - 16),
    minHeight = Math.min(400, innerHeight - 24);
  if (edge.includes('w')) left = Math.max(8, Math.min(left + dx, right - minWidth));
  if (edge.includes('e')) right = Math.min(innerWidth - 8, Math.max(right + dx, left + minWidth));
  if (edge.includes('n')) top = Math.max(8, Math.min(top + dy, bottom - minHeight));
  if (edge.includes('s')) bottom = Math.min(innerHeight - 8, Math.max(bottom + dy, top + minHeight));
  return { x: left, y: top, width: right - left, height: bottom - top };
}
export function useAgentWindow() {
  const [frame, setFrame] = useState(initial);
  const [full, setFull] = useState(false);
  const gesture = useRef<{ mode: Mode; edge: ResizeEdge; x: number; y: number; start: Frame } | null>(null);
  useEffect(() => {
    const resize = () => setFrame((f) => clamp(f));
    addEventListener('resize', resize);
    return () => removeEventListener('resize', resize);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem('sprintlens.agent.window', JSON.stringify(frame));
    } catch {
      /* optional persistence */
    }
  }, [frame]);
  useEffect(() => {
    if (!full) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [full]);
  const start = (mode: Mode, edge: ResizeEdge, e: PointerEvent<HTMLElement>) => {
    if (full || e.button !== 0) return;
    if (mode === 'move' && (e.target as HTMLElement).closest('button, a, input, select, textarea')) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    gesture.current = { mode, edge, x: e.clientX, y: e.clientY, start: frame };
  };
  const move = (e: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g) return;
    const dx = e.clientX - g.x,
      dy = e.clientY - g.y;
    setFrame(
      clamp(
        g.mode === 'move'
          ? { ...g.start, x: g.start.x + dx, y: g.start.y + dy }
          : resized(g.start, g.edge, dx, dy)
      )
    );
  };
  const stop = () => {
    gesture.current = null;
  };
  const keyboard = (mode: Mode, edge: ResizeEdge, e: KeyboardEvent<HTMLElement>) => {
    if (
      full ||
      e.target !== e.currentTarget ||
      !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)
    )
      return;
    e.preventDefault();
    const dx = e.key === 'ArrowLeft' ? -20 : e.key === 'ArrowRight' ? 20 : 0,
      dy = e.key === 'ArrowUp' ? -20 : e.key === 'ArrowDown' ? 20 : 0;
    setFrame((f) => clamp(mode === 'move' ? { ...f, x: f.x + dx, y: f.y + dy } : resized(f, edge, dx, dy)));
  };
  const controls = (mode: Mode, edge: ResizeEdge = 'se') => ({
    onPointerDown: (e: PointerEvent<HTMLElement>) => start(mode, edge, e),
    onPointerMove: move,
    onPointerUp: stop,
    onPointerCancel: stop,
    onLostPointerCapture: stop,
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => keyboard(mode, edge, e),
  });
  return { frame, full, setFull, controls };
}
