import { describe, expect, it } from "vitest";

import { extractBindParams, reconcileParamSchema } from "./bindParams";

describe("extractBindParams", () => {
  it("detects and deduplicates named bind parameters", () => {
    expect(
      extractBindParams(
        "SELECT * FROM orders WHERE customer_id = :customer_id OR owner_id = :customer_id AND status = :status",
      ),
    ).toEqual(["customer_id", "status"]);
  });

  it("ignores bind-like text inside string literals", () => {
    expect(extractBindParams("SELECT ':not_a_bind' label FROM dual WHERE id = :id")).toEqual([
      "id",
    ]);
  });
});

describe("reconcileParamSchema", () => {
  it("adds detected binds so the Parameters step does not depend on preview success", () => {
    expect(reconcileParamSchema("SELECT * FROM orders WHERE id = :order_id", {})).toEqual({
      order_id: { type: "string", required: true, default: null },
    });
  });

  it("preserves existing descriptors and removes binds no longer in the SQL", () => {
    const existing = {
      old_id: { type: "string" as const, required: true, default: null },
      limit: { type: "integer" as const, required: false, default: 10 },
    };

    expect(
      reconcileParamSchema("SELECT * FROM orders FETCH FIRST :limit ROWS ONLY", existing),
    ).toEqual({
      limit: existing.limit,
    });
  });
});
