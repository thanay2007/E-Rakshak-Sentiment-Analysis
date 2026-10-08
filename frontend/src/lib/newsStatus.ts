/** News support is evidence to review, rather than proof that a post is true. */
export function newsStatusLabel(verdict?: string): string {
  switch (verdict?.toLowerCase().replaceAll("_", " ")) {
    case "corroborated": return "Supported by news reports";
    case "partially corroborated": return "Some support in news reports";
    case "uncorroborated": return "No support found in news reports";
    default: return verdict ?? "";
  }
}
