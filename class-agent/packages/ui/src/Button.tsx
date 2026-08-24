import type { ButtonHTMLAttributes } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "plain" | "outline";
}

export function Button({
  className = "",
  type = "button",
  variant = "plain",
  ...props
}: ButtonProps) {
  const classes = ["ca-button", className].filter(Boolean).join(" ");

  return <button {...props} className={classes} data-variant={variant} type={type} />;
}
