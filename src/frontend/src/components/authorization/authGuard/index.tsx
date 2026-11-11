import { useEffect } from "react";
import {
  IS_AUTO_LOGIN,
  TERRAFLOW_ACCESS_TOKEN_EXPIRE_SECONDS,
  TERRAFLOW_ACCESS_TOKEN_EXPIRE_SECONDS_ENV,
} from "@/constants/constants";
import { useRefreshAccessToken } from "@/controllers/API/queries/auth";
import { CustomNavigate } from "@/customization/components/custom-navigate";
import useAuthStore from "@/stores/authStore";

// Where an unauthenticated visitor is sent. Only the site root carries no
// destination: here "/" opens the canvas workspace, so "/flows" (with its
// filter) must be kept, or a momentarily unconfirmed session on a full page
// load ends on a canvas instead of the list.
export function loginRedirectTarget(pathname: string, search = ""): string {
  if (pathname === "/" || pathname.includes("login")) {
    return "/login";
  }
  return `/login?redirect=${encodeURIComponent(pathname + search)}`;
}

export const ProtectedRoute = ({ children }) => {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const { mutate: mutateRefresh } = useRefreshAccessToken();
  const autoLogin = useAuthStore((state) => state.autoLogin);
  const isAutoLoginEnv = IS_AUTO_LOGIN;
  const testMockAutoLogin = sessionStorage.getItem("testMockAutoLogin");

  const shouldRedirect =
    !isAuthenticated &&
    autoLogin !== undefined &&
    (!autoLogin || !isAutoLoginEnv);

  useEffect(() => {
    const envRefreshTime = TERRAFLOW_ACCESS_TOKEN_EXPIRE_SECONDS_ENV;
    const automaticRefreshTime = TERRAFLOW_ACCESS_TOKEN_EXPIRE_SECONDS;

    const accessTokenTimer = isNaN(envRefreshTime)
      ? automaticRefreshTime
      : envRefreshTime;

    const intervalFunction = () => {
      mutateRefresh();
    };

    if (autoLogin !== undefined && !autoLogin && isAuthenticated) {
      const intervalId = setInterval(intervalFunction, accessTokenTimer * 1000);
      intervalFunction();
      return () => clearInterval(intervalId);
    }
  }, [isAuthenticated]);

  if (shouldRedirect || testMockAutoLogin) {
    return (
      <CustomNavigate
        to={loginRedirectTarget(
          window.location.pathname,
          window.location.search,
        )}
        replace
      />
    );
  } else {
    return children;
  }
};
