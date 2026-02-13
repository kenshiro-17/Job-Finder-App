import { fetchMe } from "./api.js";

export function setSession(accessToken, username) {
  window.localStorage.setItem("job_finder_token", accessToken);
  window.localStorage.setItem("job_finder_username", username || "");
}

export function clearSession() {
  window.localStorage.removeItem("job_finder_token");
  window.localStorage.removeItem("job_finder_username");
}

export async function ensureAuthenticated() {
  const token = window.localStorage.getItem("job_finder_token");
  if (!token) {
    window.location.href = "/login.html";
    return null;
  }
  try {
    return await fetchMe();
  } catch (_err) {
    clearSession();
    window.location.href = "/login.html";
    return null;
  }
}

export function wireLogout(buttonId = "logout-btn") {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  btn.addEventListener("click", () => {
    clearSession();
    window.location.href = "/login.html";
  });
}
