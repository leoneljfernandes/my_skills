import { expect, it } from "vitest";

import { safeNext } from "../generated/safe-next";

it.each(["//evil.com", "/\\evil.com", "https://evil.com", "/\t/evil.com", "javascript:alert(1)"])(
  "safeNext_rejects_%s",
  (raw) => {
    expect(safeNext(raw)).toBe("/");
  },
);

it("safeNext_keeps_internal_path_and_query", () => {
  expect(safeNext("/a?b=1")).toBe("/a?b=1");
  expect(safeNext(null)).toBe("/");
});
