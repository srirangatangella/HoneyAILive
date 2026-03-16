export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function generateId() {
  return Math.random().toString(36).slice(2);
}
