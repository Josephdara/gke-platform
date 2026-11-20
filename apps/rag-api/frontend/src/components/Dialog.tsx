import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';

interface DialogProps {
  title: string;
  children: ReactNode;
  onClose: () => void;
  drawer?: boolean;
  fallbackFocus?: () => void;
}

/** Native modal dialogs provide focus containment and inert background content. */
export function Dialog({ title, children, onClose, drawer = false, fallbackFocus }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const fallback = useRef(fallbackFocus);
  useEffect(() => {
    const element = ref.current;
    const opener = document.activeElement;
    const restoreFallback = fallback.current;
    element?.showModal();
    return () => {
      element?.close();
      if (opener instanceof HTMLElement && opener.isConnected && !opener.hasAttribute('disabled') && opener.getClientRects().length > 0) opener.focus();
      else restoreFallback?.();
    };
  }, []);

  return <dialog
    ref={ref}
    className={drawer ? 'dialog drawer' : 'dialog'}
    aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
    onKeyDown={(event) => {
      if (event.key !== 'Tab') return;
      const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex="0"]',
      )).filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first && last) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last && first) { event.preventDefault(); first.focus(); }
    }}
  >
    <div className="dialog-content">
      <div className="dialog-heading">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="button quiet" onClick={onClose} aria-label={`Close ${title.toLowerCase()}`}>Close</button>
      </div>
      {children}
    </div>
  </dialog>;
}
