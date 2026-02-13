import { loginUser, registerUser } from "./api.js";
import { setSession } from "./authSession.js";
import { showToast } from "./utils.js";

const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  try {
    const response = await loginUser({ username, password });
    setSession(response.access_token, response.username);
    window.location.href = "/";
  } catch (error) {
    showToast(error.response?.data?.detail || "Login failed.");
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("register-username").value.trim();
  const password = document.getElementById("register-password").value;
  try {
    const response = await registerUser({ username, password });
    setSession(response.access_token, response.username);
    window.location.href = "/";
  } catch (error) {
    showToast(error.response?.data?.detail || "Registration failed.");
  }
});
