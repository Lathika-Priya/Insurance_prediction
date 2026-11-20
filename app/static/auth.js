"use strict";
const isRegister = window.location.pathname === "/register";
const form = document.getElementById("auth-form");
const password = document.getElementById("password");
const confirmPassword = document.getElementById("confirm-password");
const errorBox = document.getElementById("auth-error");
const submitButton = document.getElementById("auth-submit");
const submitLabel = document.getElementById("submit-label");

if (isRegister) {
  document.title = "Create an account | Carewise";
  document.getElementById("auth-title").textContent = "Make room for clarity.";
  document.getElementById("auth-subtitle").textContent = "Create your account to start your personal assessment.";
  document.getElementById("switch-prompt").textContent = "Already have an account?";
  const switchLink = document.getElementById("switch-link");
  switchLink.textContent = "Sign in"; switchLink.href = "/login";
  document.getElementById("login-tab").classList.remove("active");
  document.getElementById("login-tab").removeAttribute("aria-current");
  document.getElementById("register-tab").classList.add("active");
  document.getElementById("register-tab").setAttribute("aria-current", "page");
  for (const id of ["name-field", "confirm-field", "password-hint"]) document.getElementById(id).hidden = false;
  for (const input of [document.getElementById("full-name"), confirmPassword]) {
    input.disabled = false; input.required = true;
  }
  password.minLength = 8;
  password.autocomplete = "new-password";
  password.placeholder = "Create a password";
  submitLabel.textContent = "Create account";
  form.action = "/api/auth/register";
}
if (window.location.pathname === "/admin/login") {
  document.title = "Administrator sign in | Carewise";
  document.getElementById("auth-title").textContent = "Administrator sign in.";
  document.getElementById("auth-subtitle").textContent = "Manage sample plans, pricing rules, and user accounts.";
  document.querySelector(".auth-tabs").hidden = true;
  document.getElementById("switch-prompt").textContent = "User account?";
  const link = document.getElementById("switch-link");
  link.href = "/login"; link.textContent = "User sign in";
  form.action = "/api/auth/admin-login";
}
const notice = document.getElementById("auth-notice");
const reason = new URLSearchParams(location.search);
if (reason.has("password_changed")) {
  notice.textContent = "Password changed. Sign in with your new password.";
  notice.hidden = false;
} else if (reason.has("expired")) {
  notice.textContent = "Your session has ended. Sign in again to continue.";
  notice.hidden = false;
} else if (reason.has("signed_out")) {
  notice.textContent = "You have been signed out.";
  notice.hidden = false;
}
for (const button of document.querySelectorAll("[data-password]")) {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.password);
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    button.textContent = visible ? "Hide" : "Show";
    button.setAttribute("aria-pressed", String(visible));
    button.setAttribute("aria-label", (visible ? "Hide " : "Show ") + (input === password ? "password" : "confirmation password"));
  });
}
function checkConfirmation() {
  confirmPassword.setCustomValidity(isRegister && confirmPassword.value !== password.value ? "Passwords do not match." : "");
}
password.addEventListener("input", checkConfirmation);
confirmPassword.addEventListener("input", checkConfirmation);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  checkConfirmation();
  if (!form.reportValidity() || submitButton.disabled) return;
  errorBox.hidden = true;
  const data = Object.fromEntries(new FormData(form));
  data.remember_me = form.elements.remember_me.checked;
  submitButton.disabled = true;
  form.setAttribute("aria-busy", "true");
  submitButton.querySelector(".spinner").hidden = false;
  submitLabel.textContent = isRegister ? "Creating account..." : "Signing in...";
  try {
    const response = await fetch(form.action, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(data),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      throw new Error(Array.isArray(detail) ? detail.map(item => item.msg.replace(/^Value error, /, "")).join(" ") : detail || "Unable to sign in. Please try again.");
    }
    window.location.replace(result.user.role === "admin" ? "/admin" : "/home");
  } catch (error) {
    errorBox.textContent = error instanceof TypeError ? "We couldn't reach the server. Check your connection and try again." : error.message;
    errorBox.hidden = false;
    errorBox.focus();
  } finally {
    submitButton.disabled = false;
    form.setAttribute("aria-busy", "false");
    submitButton.querySelector(".spinner").hidden = true;
    submitLabel.textContent = isRegister ? "Create account" : "Sign in";
  }
});
window.addEventListener("pageshow", (event) => { if (event.persisted) window.location.reload(); });
