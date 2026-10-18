import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function compactNumber(value: unknown) {
  const number = Number(value || 0);
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(number);
}

export function percent(value: unknown) {
  const number = Number(value || 0);
  return `${(number * 100).toFixed(2)}%`;
}
