import { refusalReason } from "../run-evidence";

describe("scientific refusals in synthetic native tool outputs", () => {
  it("exposes refusal in a valid transport response", () => {
    const run = {
      valid: true,
      data: {
        outputs: {
          decision: {
            type: "data",
            message: {
              raw: {
                data: {
                  passed: false,
                  reason_code: "grid_mismatch",
                  failed_checks: ["shape"],
                },
              },
            },
          },
        },
      },
    };
    expect(refusalReason(run.data)).toBe("grid_mismatch · shape");
  });
  it("does not infer refusal from arbitrary false fields or a passing gate", () => {
    expect(
      refusalReason({
        outputs: {
          success: true,
          execution_blocked: false,
          passed: true,
          has_cloud: false,
        },
      }),
    ).toBeNull();
    expect(refusalReason({ outputs: { passed: false } })).toBeNull();
  });
});
