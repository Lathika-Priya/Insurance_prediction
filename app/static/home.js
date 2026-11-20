"use strict";
let homeCsrf = "";
const errorBox = document.getElementById("session-error");
async function loadHome() {
  try {
    const sessionResponse = await fetch("/api/auth/me", {cache: "no-store"});
    if (sessionResponse.status === 401) { location.replace("/login?expired=1"); return; }
    if (!sessionResponse.ok) throw new Error("Unable to load your account. Refresh the page to try again.");
    const session = await sessionResponse.json();
    homeCsrf = session.csrf_token;
    document.getElementById("user-name").textContent = session.user.name;
    document.getElementById("user-email").textContent = session.user.email;
    document.getElementById("welcome-name").textContent = session.user.name.split(" ")[0];
    document.getElementById("user-avatar").textContent = session.user.name.trim().split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
    const response = await fetch("/api/assessments/latest", {cache: "no-store"});
    if (response.status === 401) { location.replace("/login?expired=1"); return; }
    if (!response.ok) throw new Error("Unable to load your recommendations. Refresh the page to try again.");
    const {assessment} = await response.json();
    if (!assessment) {
      document.getElementById("first-assessment").hidden = false;
      document.getElementById("home-subtitle").textContent = "Start your first assessment to discover your health and coverage profile.";
      return;
    }
    document.getElementById("saved-assessment").hidden = false;
    document.getElementById("retake-button").hidden = false;
    document.getElementById("home-subtitle").textContent = "Review your latest recommendations or take a new assessment.";
    const completed = new Date(assessment.completed_at);
    document.getElementById("completed-at").textContent = "Completed " + completed.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
    const best = assessment.result.recommendations[0];
    document.getElementById("best-plan").textContent = best ? best.plan_name : "No matching plan";
    document.getElementById("best-premium").textContent = best ? inr(best.premium_year1) : "Not available";
    document.getElementById("best-cover").textContent = best ? inr(best.sum_insured) : "Not available";
    render(assessment.result, false);
  } catch (error) {
    errorBox.textContent = error instanceof TypeError ? "We couldn't reach the server. Refresh the page to try again." : error.message;
    errorBox.hidden = false;
  } finally {
    document.getElementById("home-loading").hidden = true;
  }
}
document.getElementById("logout-button").addEventListener("click", async event => {
  const button = event.currentTarget;
  if (!homeCsrf) { location.reload(); return; }
  button.disabled = true;
  try {
    const response = await fetch("/api/auth/logout", {method: "POST", headers: {"X-CSRF-Token": homeCsrf}});
    if (!response.ok && response.status !== 401) throw new Error("Please try signing out again.");
    location.replace("/login?signed_out=1");
  } catch (error) {
    errorBox.textContent = "We couldn't sign you out. Check your connection and try again.";
    errorBox.hidden = false;
    button.disabled = false;
  }
});
window.addEventListener("pageshow", event => { if (event.persisted) location.reload(); });
loadHome();
