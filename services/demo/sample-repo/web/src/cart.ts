export interface CartLine {
  sku: string;
  name: string;
  priceCents: number;
  quantity: number;
}

export function subtotalCents(lines: CartLine[]): number {
  return lines.reduce((sum, line) => sum + line.priceCents * line.quantity, 0);
}
