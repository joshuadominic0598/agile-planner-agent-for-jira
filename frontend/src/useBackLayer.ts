import { useEffect, useRef, type RefObject } from 'react';

let pendingBack: Promise<void> = Promise.resolve();

// Same-URL history entries let browser back gestures dismiss the current screen first.
export function useBackLayer(active: boolean, back: () => void, surface?: RefObject<HTMLElement | null>) {
  const callback = useRef(back);
  callback.current = back;
  useEffect(() => {
    if (!active) return;
    const token = crypto.randomUUID();
    const layers = () => (history.state?.agileplannerLayers || []) as string[];
    let registered = false;
    let disposed = false;
    void pendingBack.then(() => {
      if (disposed) return;
      history.pushState({ ...history.state, agileplannerLayers: [...layers(), token] }, '', location.href);
      registered = true;
    });
    let popped = false;
    const pop = () => {
      if (registered && !layers().includes(token)) {
        popped = true;
        callback.current();
      }
    };
    let start: { x: number; y: number } | null = null;
    const touchStart = (event: TouchEvent) => {
      if (!registered || layers().at(-1) !== token || event.touches.length !== 1) return;
      const target = event.target as HTMLElement;
      if (surface?.current && !surface.current.contains(target)) return;
      if (target.closest('input,textarea,select,button,a,[contenteditable=true]')) return;
      start = { x: event.touches[0].clientX, y: event.touches[0].clientY };
    };
    const touchEnd = (event: TouchEvent) => {
      if (!start || !event.changedTouches.length) return;
      const dx = event.changedTouches[0].clientX - start.x;
      const dy = Math.abs(event.changedTouches[0].clientY - start.y);
      start = null;
      if (dx > 90 && dy < dx * 0.45 && layers().at(-1) === token) {
        if (event.cancelable) event.preventDefault();
        history.back();
      }
    };
    window.addEventListener('popstate', pop);
    document.addEventListener('touchstart', touchStart, { passive: true });
    document.addEventListener('touchend', touchEnd, { passive: false });
    return () => {
      disposed = true;
      window.removeEventListener('popstate', pop);
      document.removeEventListener('touchstart', touchStart);
      document.removeEventListener('touchend', touchEnd);
      if (registered && !popped && layers().at(-1) === token) {
        pendingBack = new Promise<void>((resolve) =>
          window.addEventListener('popstate', () => resolve(), { once: true })
        );
        history.back();
      }
    };
  }, [active, surface]);
}
