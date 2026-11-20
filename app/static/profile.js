"use strict";
(async () => {
  try {
    await accountReady;
    const profile = await api("/api/profile");
    document.getElementById("profile-name").textContent = profile.name;
    document.getElementById("profile-email").textContent = profile.email;
    document.getElementById("profile-role").textContent = profile.role === "admin" ? "Administrator" : "User";
    document.getElementById("profile-joined").textContent = new Date(profile.created_at * 1000).toLocaleDateString();
    document.getElementById("profile-assessment").textContent = profile.last_assessment_at ? new Date(profile.last_assessment_at).toLocaleString() : "No assessment completed";
    document.querySelector("#password-form button").disabled = false;
  } catch (error) { showNotice(error.message, true); }
})();
const passwordForm = document.getElementById("password-form");
const confirmNew = document.getElementById("confirm-new-password");
function matchPasswords() { confirmNew.setCustomValidity(confirmNew.value === document.getElementById("new-password").value ? "" : "Passwords do not match."); }
passwordForm.addEventListener("input", matchPasswords);
passwordForm.addEventListener("submit", async event => {
  event.preventDefault();
  matchPasswords();
  if (!passwordForm.reportValidity()) return;
  const button = passwordForm.querySelector("button"); button.disabled = true;
  try {
    await api("/api/profile/password", {method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(passwordForm)))});
    passwordForm.reset();
    location.replace("/login?password_changed=1");
  } catch (error) { showNotice(error.message, true); button.disabled = false; }
});
