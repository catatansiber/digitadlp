import type { ReactNode } from "react";

export function Chip({ tone, children }: { tone: "pub" | "int" | "rah" | "neu"; children: ReactNode }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}
