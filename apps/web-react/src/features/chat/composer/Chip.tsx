/**
 * WHAT: Reusable pill-shaped chip for the composer toolbar (Backend, Model, Workspace, Reasoning, Toolsets).
 * WHERE YOU SEE IT: Bottom toolbar row, shows current selection with LED status indicator.
 * CLICK: Opens a dropdown menu (ComposerPopover) anchored to this chip.
 * SAVES TO: Varies by chip type — Backend switches adapter, Model saves to session, Workspace sets folder.
 * HIDES WHEN: Container width < 520px (moves to overflow menu on mobile/narrow chat columns).
 */

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import "./chips.css";

export interface ChipProps {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  title?: string;
  maxWidth?: string;
  ledColor?: "emerald" | "purple" | "cyan" | "amber" | "red";
  ledPulse?: boolean;
}

function SwitchboardLED({ active = true, color = "emerald", pulse = false }: { active?: boolean; color?: "emerald" | "purple" | "cyan" | "amber" | "red"; pulse?: boolean }) {
  const colorMap = {
    emerald: "#10b981",
    purple: "#a855f7",
    cyan: "#08ebf1",
    amber: "#f59e0b",
    red: "#ef4444",
  };
  const activeColor = colorMap[color] || colorMap.emerald;
  
  return (
    <span
      className={`switchboard-led switchboard-led--${color} ${active ? "switchboard-led--active" : ""} ${pulse ? "switchboard-led--pulse" : ""}`}
      style={{ "--led-color": activeColor } as React.CSSProperties}
    />
  );
}

export function Chip({ icon, label, onClick, title, maxWidth, ledColor, ledPulse }: ChipProps) {
  const [hover, setHover] = useState(false);
  
  return (
    <button
      type="button"
      title={title || label}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="composer-chip"
      style={{ maxWidth: maxWidth || "14rem" }}
    >
      {ledColor && <SwitchboardLED active={true} color={ledColor} pulse={ledPulse} />}
      <span className="composer-chip__icon">{icon}</span>
      <span className="composer-chip__label">{label}</span>
      <ChevronDown size={9} className="composer-chip__chevron" />
    </button>
  );
}
