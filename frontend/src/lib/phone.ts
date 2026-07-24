// Bangladeshi mobile-number validation + normalization.
// Mirrors backend/app/schemas.py::normalize_bd_phone so the two never diverge.

const BD_PHONE_RE = /^01[3-9]\d{8}$/;

/** Digits-only, tolerating +880 / 880 / dropped-leading-zero forms. */
export function normalizeBdPhone(raw: string): string {
  let digits = (raw || "").replace(/\D/g, "");
  if (digits.startsWith("880")) digits = digits.slice(3);
  if (digits.length === 10 && digits.startsWith("1")) digits = "0" + digits;
  return digits;
}

/** True when `raw` normalizes to a valid 11-digit BD mobile number. */
export function isValidBdPhone(raw: string): boolean {
  return BD_PHONE_RE.test(normalizeBdPhone(raw));
}

/** Pretty display: 01712-345678. */
export function formatBdPhone(raw: string): string {
  const d = normalizeBdPhone(raw);
  return BD_PHONE_RE.test(d) ? `${d.slice(0, 5)}-${d.slice(5)}` : raw;
}
