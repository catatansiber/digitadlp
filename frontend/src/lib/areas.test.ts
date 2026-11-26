import { normalizeBox } from "./areas";

test("normalizeBox handles reversed drag, clamps, rejects tiny", () => {
  expect(normalizeBox(80, 60, 20, 10, 100, 200)).toEqual({ x0: 0.2, y0: 0.05, x1: 0.8, y1: 0.3 });
  expect(normalizeBox(-10, -5, 150, 300, 100, 200)).toEqual({ x0: 0, y0: 0, x1: 1, y1: 1 });
  expect(normalizeBox(10, 10, 10.2, 50, 100, 100)).toBeNull();
  expect(normalizeBox(10, 10, 50, 10.4, 100, 100)).toBeNull();
  expect(normalizeBox(0, 0, 10, 10, 0, 100)).toBeNull();
});
