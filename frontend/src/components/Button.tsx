import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "default" | "danger" };

export function Button({ variant = "default", className, type = "button", ...rest }: Props) {
  const cls = ["btn", variant !== "default" ? variant : "", className ?? ""].filter(Boolean).join(" ");
  return <button type={type} className={cls} {...rest} />;
}
