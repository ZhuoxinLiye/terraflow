/** Scientific refusal can be a valid tool return; do not label it success. */
export function refusalReason(value: unknown, depth = 0): string | null {
  if (depth > 8 || value == null) return null;
  if (typeof value === "string") {
    if (!/^[\s]*[[{]/.test(value)) return null;
    try {
      return refusalReason(JSON.parse(value), depth + 1);
    } catch {
      return null;
    }
  }
  if (typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (
    record.execution_blocked === true ||
    ((record.passed === false || record.success === false) &&
      (record.reason_code || Array.isArray(record.failed_checks)))
  ) {
    return (
      Array.from(
        new Set(
          [
            record.reason_code,
            ...(Array.isArray(record.failed_checks)
              ? record.failed_checks
              : []),
          ].filter((s) => typeof s === "string" && s),
        ),
      ).join(" · ") || "科学检查未通过"
    );
  }
  for (const child of Object.values(record)) {
    const reason = refusalReason(child, depth + 1);
    if (reason) return reason;
  }
  return null;
}
