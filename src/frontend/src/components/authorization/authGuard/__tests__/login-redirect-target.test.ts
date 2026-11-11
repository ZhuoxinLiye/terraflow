jest.mock("@/controllers/API/queries/auth", () => ({
  useRefreshAccessToken: jest.fn(),
}));
jest.mock("@/customization/components/custom-navigate", () => ({
  CustomNavigate: () => null,
}));
jest.mock("@/stores/authStore", () => ({ __esModule: true, default: jest.fn() }));
jest.mock("@/constants/constants", () => ({
  IS_AUTO_LOGIN: false,
  TERRAFLOW_ACCESS_TOKEN_EXPIRE_SECONDS: 60,
  TERRAFLOW_ACCESS_TOKEN_EXPIRE_SECONDS_ENV: Number.NaN,
}));

import { loginRedirectTarget } from "../index";

describe("loginRedirectTarget", () => {
  it("sends the site root and the login page to /login without a destination", () => {
    expect(loginRedirectTarget("/")).toBe("/login");
    expect(loginRedirectTarget("/login", "?redirect=/flows")).toBe("/login");
  });

  it("keeps the workflow list as the destination", () => {
    expect(loginRedirectTarget("/flows")).toBe("/login?redirect=%2Fflows");
  });

  it("keeps the list filter so the workbench subset survives a login bounce", () => {
    const target = loginRedirectTarget("/flows", "?source=workbench");
    expect(new URLSearchParams(target.split("?")[1]).get("redirect")).toBe(
      "/flows?source=workbench",
    );
  });

  it("keeps a canvas path as before", () => {
    expect(loginRedirectTarget("/flow/abc")).toBe(
      "/login?redirect=%2Fflow%2Fabc",
    );
  });
});
