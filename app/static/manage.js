"use strict";
let accountCsrf = "";
function showNotice(message, error = false) {
  const box = document.getElementById("page-notice");
  box.textContent = message;
  box.classList.toggle("error-notice", error);
  box.hidden = false;
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, cache: "no-store", headers: {
    "Content-Type": "application/json", "X-CSRF-Token": accountCsrf, ...(options.headers || {})
  }});
  if (response.status === 401) { location.replace("/login?expired=1"); throw new Error("Please sign in again."); }
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(Array.isArray(detail) ? detail.map(item => item.msg.replace(/^Value error, /, "")).join(" ") : detail || "The request failed.");
  }
  return data;
}
const accountReady = (async () => {
  try {
    const session = await api("/api/auth/me");
    accountCsrf = session.csrf_token;
    document.getElementById("user-name").textContent = session.user.name;
    document.getElementById("user-email").textContent = session.user.email;
    document.getElementById("user-avatar").textContent = session.user.name.slice(0, 1).toUpperCase();
    for (const link of document.querySelectorAll("[data-account-home]")) link.href = session.user.role === "admin" ? "/admin" : "/home";
    return session.user;
  } catch (error) { showNotice(error.message, true); throw error; }
})();
document.getElementById("logout-button").addEventListener("click", async event => {
  const button = event.currentTarget;
  button.disabled = true;
  try { await accountReady; await api("/api/auth/logout", {method: "POST"}); location.replace("/login?signed_out=1"); }
  catch (error) { showNotice(error.message, true); button.disabled = false; }
});
window.addEventListener("pageshow", event => { if (event.persisted) location.reload(); });
