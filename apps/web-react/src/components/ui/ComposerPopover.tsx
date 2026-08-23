/**
 * WHAT: Portal-based dropdown menu for composer chips (Model, Backend, Workspace, etc.).
 * WHERE YOU SEE IT: Opens above/below chip buttons in composer toolbar.
 * DESKTOP: Fixed position above anchor, auto-flips if off-screen.
 * MOBILE (≤640px): Bottom sheet modal with backdrop, smooth slide animation.
 * CLOSE: Outside click (backdrop), Escape key, or selecting an option.
 * DONOR REFERENCE: Hermes WebUI ui.js (_positionModelDropdown, closeSiblingsThenOpen)
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface ComposerPopoverProps {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement | null>;
  children: React.ReactNode;
  align?: "left" | "right";
  minWidth?: string;
  maxWidth?: string;
  width?: string;
  title?: string;
}

const H = {
  backdrop: "rgba(0, 0, 0, 0.6)",
  surface: "#131622",
  border: "rgba(255, 255, 255, 0.08)",
};

export function ComposerPopover({
  isOpen,
  onClose,
  anchorRef,
  children,
  align = "left",
  minWidth,
  maxWidth,
  width,
  title,
}: ComposerPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number; right?: number }>({ top: 0, left: 0 });
  const [isMobile, setIsMobile] = useState(false);

  // Check if we're in mobile viewport
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth <= 640);
    };
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Calculate position based on anchor element (desktop only)
  const updatePosition = useCallback(() => {
    if (isMobile) return; // Mobile uses bottom sheet, no positioning needed
    
    const anchor = anchorRef.current;
    const popover = popoverRef.current;
    if (!anchor || !popover) return;

    const anchorRect = anchor.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Position above the anchor (bottom of popover aligns with top of anchor)
    const gap = 8; // 0.5rem gap
    const top = anchorRect.top - popoverRect.height - gap;
    
    // Horizontal positioning
    let left: number | undefined;
    let right: number | undefined;

    if (align === "right") {
      // Align right edge of popover with right edge of anchor
      const initialLeft = anchorRect.right - popoverRect.width;
      
      // Check if it would go off left edge
      if (initialLeft < 8) {
        // Flip to align left instead
        left = anchorRect.left;
      } else {
        left = initialLeft;
      }
    } else {
      // Align left edge of popover with left edge of anchor
      const initialLeft = anchorRect.left;
      
      // Check if it would go off right edge
      if (initialLeft + popoverRect.width > viewportWidth - 8) {
        // Flip to align right edge instead
        right = viewportWidth - anchorRect.right;
      } else {
        left = initialLeft;
      }
    }

    // Ensure popover doesn't go off top of screen
    const finalTop = Math.max(8, top);
    
    // Ensure popover doesn't go off bottom of screen
    if (finalTop + popoverRect.height > viewportHeight - 8) {
      // Reposition to open below instead (fallback)
      const belowTop = anchorRect.bottom + gap;
      setPosition({ top: belowTop, left: left!, right });
    } else {
      setPosition({ top: finalTop, left: left!, right });
    }
  }, [anchorRef, align, isMobile]);

  // Update position on mount, when isOpen changes, and on window resize/scroll
  useEffect(() => {
    if (!isOpen || isMobile) return;
    
    updatePosition();
    
    const handleResize = () => updatePosition();
    const handleScroll = () => updatePosition();
    
    window.addEventListener("resize", handleResize);
    window.addEventListener("scroll", handleScroll, true);
    
    return () => {
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [isOpen, isMobile, updatePosition]);

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Close on outside click (backdrop for mobile, anywhere for desktop)
  useEffect(() => {
    if (!isOpen) return;
    
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      // Don't close if click is inside the popover or on the anchor
      if (popoverRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen, onClose, anchorRef]);

  if (!isOpen) return null;

  // Mobile: Bottom sheet modal with backdrop
  if (isMobile) {
    return createPortal(
      <>
        {/* Backdrop */}
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: H.backdrop,
            zIndex: 1000,
            backdropFilter: "blur(4px)",
          }}
          onClick={onClose}
        />
        
        {/* Bottom Sheet */}
        <div
          ref={popoverRef}
          data-composer-popover-mobile
          style={{
            position: "fixed",
            left: "12px",
            right: "12px",
            bottom: "12px",
            zIndex: 1001,
            background: H.surface,
            border: `1px solid ${H.border}`,
            borderRadius: "12px",
            boxShadow: "0 -4px 24px rgba(0, 0, 0, 0.4)",
            fontSize: "0.75rem",
            overflow: "hidden",
            maxHeight: "min(70vh, 640px)",
            display: "flex",
            flexDirection: "column",
            animation: "slideUp 0.3s cubic-bezier(0.32, 0.72, 0.16, 1)",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header with close button */}
          {title && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 16px",
                borderBottom: `1px solid ${H.border}`,
                background: "rgba(255, 255, 255, 0.02)",
              }}
            >
              <span style={{ fontSize: "0.8125rem", fontWeight: 600, color: "#8e8ea0" }}>
                {title}
              </span>
              <button
                type="button"
                onClick={onClose}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "32px",
                  height: "32px",
                  borderRadius: "8px",
                  border: "none",
                  background: "rgba(255, 255, 255, 0.04)",
                  color: "#8e8ea0",
                  cursor: "pointer",
                  transition: "background 0.15s, color 0.15s",
                }}
              >
                <X size={16} />
              </button>
            </div>
          )}
          
          {/* Content (scrollable) */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              overscrollBehavior: "contain",
              WebkitOverflowScrolling: "touch",
            }}
          >
            {children}
          </div>
        </div>
        
        {/* Animation keyframes */}
        <style>{`
          @keyframes slideUp {
            from {
              transform: translateY(100%);
              opacity: 0;
            }
            to {
              transform: translateY(0);
              opacity: 1;
            }
          }
        `}</style>
      </>,
      document.body
    );
  }

  // Desktop: Fixed position above anchor
  return createPortal(
    <div
      ref={popoverRef}
      data-composer-popover
      style={{
        position: "fixed",
        top: `${position.top}px`,
        ...(position.left !== undefined ? { left: `${position.left}px` } : {}),
        ...(position.right !== undefined ? { right: `${position.right}px` } : {}),
        zIndex: 1000,
        minWidth: minWidth || "auto",
        maxWidth: maxWidth || "min(22rem, 88vw)",
        width: width || "auto",
        borderRadius: "12px",
        border: `1px solid ${H.border}`,
        background: H.surface,
        boxShadow: "0 1rem 3rem rgba(0, 0, 0, 0.7)",
        fontSize: "0.75rem",
        overflow: "hidden",
        backdropFilter: "blur(8px)",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>,
    document.body
  );
}
