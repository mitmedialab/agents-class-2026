import type { InputHTMLAttributes } from "react";

export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
}

export function TextInput({ className = "", id, label, ...props }: TextInputProps) {
  const inputId = id ?? `field-${label.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}`;
  const classes = ["ca-input", className].filter(Boolean).join(" ");

  return (
    <label className="ca-field" htmlFor={inputId}>
      <span className="ca-field__label">{label}</span>
      <input {...props} className={classes} id={inputId} />
    </label>
  );
}
