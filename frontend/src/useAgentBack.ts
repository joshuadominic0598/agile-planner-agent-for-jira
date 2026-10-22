import { useEffect, useRef, type RefObject } from 'react';

function ownsHorizontalGesture(target: EventTarget | null, panel: HTMLElement) {
  if (!(target instanceof Element)) return false;
  if (target.closest('input,textarea,select,[contenteditable=true],.agent-resize')) return true;
  for (let element: Element | null = target; element && element !== panel; element = element.parentElement) {
    const style = getComputedStyle(element);
    if (element.scrollWidth > element.clientWidth + 1 && /auto|scroll/.test(style.overflowX)) return true;
  }
  return false;
}

export function useAgentBack(open: boolean, back: () => void, surface: RefObject<HTMLElement | null>) {
  const callback = useRef(back);
  callback.current = back;
  useEffect(() => {
    const panel = surface.current;
    if (!open || !panel) return;
    let touch: { id: number; x: number; y: number } | null = null;
    let distance = 0;
    let handled = false;
    let lastWheel = 0;
    const consume = (event: Event) => {
      if (event.cancelable) event.preventDefault();
      event.stopPropagation();
    };
    const touchStart = (event: TouchEvent) => {
      touch = null;
      if (event.touches.length !== 1 || ownsHorizontalGesture(event.target, panel)) return;
      if (event.target instanceof Element && event.target.closest('.agent-move')) return;
      const point = event.touches[0];
      touch = { id: point.identifier, x: point.clientX, y: point.clientY };
    };
    const touchMove = (event: TouchEvent) => {
      if (event.touches.length !== 1) touch = null;
      const point = touch && Array.from(event.touches).find((item) => item.identifier === touch!.id);
      if (!touch || !point) return;
      const dx = point.clientX - touch.x;
      if (Math.abs(dx) > 12 && Math.abs(point.clientY - touch.y) < Math.abs(dx) * 0.45) consume(event);
    };
    const touchEnd = (event: TouchEvent) => {
      const point = touch && Array.from(event.changedTouches).find((item) => item.identifier === touch!.id);
      if (!touch || !point) return;
      const dx = point.clientX - touch.x;
      const dy = Math.abs(point.clientY - touch.y);
      touch = null;
      if (Math.abs(dx) > 90 && dy < Math.abs(dx) * 0.45) {
        consume(event);
        if (dx > 0) callback.current();
      }
    };
    const touchCancel = () => {
      touch = null;
    };
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || Math.abs(event.deltaX) <= Math.abs(event.deltaY) * 1.3) return;
      if (ownsHorizontalGesture(event.target, panel)) return;
      consume(event);
      const now = performance.now();
      if (now - lastWheel > 240) {
        distance = 0;
        handled = false;
      }
      lastWheel = now;
      const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? panel.clientWidth : 1;
      distance = Math.max(0, distance - event.deltaX * scale);
      if (distance >= 90 && !handled) {
        handled = true;
        callback.current();
      }
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'BrowserBack' || (event.altKey && event.key === 'ArrowLeft')) {
        consume(event);
        callback.current();
      }
    };
    panel.addEventListener('touchstart', touchStart, { passive: true });
    panel.addEventListener('touchmove', touchMove, { passive: false });
    panel.addEventListener('touchend', touchEnd, { passive: false });
    panel.addEventListener('touchcancel', touchCancel);
    panel.addEventListener('wheel', wheel, { passive: false });
    panel.addEventListener('keydown', key);
    return () => {
      panel.removeEventListener('touchstart', touchStart);
      panel.removeEventListener('touchmove', touchMove);
      panel.removeEventListener('touchend', touchEnd);
      panel.removeEventListener('touchcancel', touchCancel);
      panel.removeEventListener('wheel', wheel);
      panel.removeEventListener('keydown', key);
    };
  }, [open, surface]);
}
