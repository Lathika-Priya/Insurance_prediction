"use strict";

const BOOL = ["smoked_100_cigarettes","heavy_alcohol","physically_active","fruit_daily","vegetables_daily","difficulty_walking","heart_disease","stroke","kidney_disease","asthma","skin_cancer"];
const NUM = ["age","height_cm","weight_kg","sleep_hours","general_health","poor_physical_health_days","poor_mental_health_days"];
const PREF = ["annual_budget_inr","min_sum_insured_inr","existing_cover_inr","risk_tolerance","horizon_years"];
const form = document.getElementById("f");
const steps = [...document.querySelectorAll(".form-step")];
const stepLinks = [...document.querySelectorAll("[data-goto]")];
const backButton = document.getElementById("back-button");
const nextButton = document.getElementById("next-button");
const goButton = document.getElementById("go");
const statusText = document.getElementById("status");
const logoutButton = document.getElementById("logout-button");
let currentStep = 0;
let furthestStep = 0;
let csrfToken = "";
let busy = false;
let sessionReady = false;

function showStep(index, focus = true) {
  currentStep = index;
  furthestStep = Math.max(furthestStep, index);
  steps.forEach((step, i) => { step.hidden = i !== index; });
  stepLinks.forEach((link, i) => {
    link.disabled = busy || !sessionReady || i > furthestStep;
    link.classList.toggle("active", i === index);
    link.classList.toggle("complete", i < index);
    if (i === index) link.setAttribute("aria-current", "step");
    else link.removeAttribute("aria-current");
  });
  backButton.hidden = index === 0;
  nextButton.hidden = index === steps.length - 1;
  goButton.hidden = index !== steps.length - 1;
  document.getElementById("step-count").textContent = "Step " + (index + 1) + " of " + steps.length;
  document.getElementById("section-count").textContent = "0" + (index + 1) + " / 05";
  document.getElementById("step-progress").style.width = ((index + 1) / steps.length * 100) + "%";
  document.querySelector(".progress-track").setAttribute("aria-valuenow", String(index + 1));
  if (focus) {
    const legend = steps[index].querySelector("legend");
    legend.tabIndex = -1;
    legend.focus({preventScroll: true});
    document.getElementById("assessment-form").scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start"});
  }
}
function validateStep(index) {
  for (const input of steps[index].querySelectorAll("input, select")) {
    if (!input.checkValidity()) {
      showStep(index, false);
      input.reportValidity();
      return false;
    }
  }
  return true;
}
nextButton.addEventListener("click", () => {
  if (sessionReady && !busy && validateStep(currentStep)) showStep(Math.min(currentStep + 1, steps.length - 1));
});
backButton.addEventListener("click", () => { if (!busy) showStep(Math.max(0, currentStep - 1)); });
stepLinks.forEach(link => link.addEventListener("click", () => {
  const target = Number(link.dataset.goto);
  if (busy || !sessionReady || target > furthestStep) return;
  if (target > currentStep) {
    for (let i = currentStep; i < target; i++) if (!validateStep(i)) return;
  }
  showStep(target);
}));

async function loadSession() {
  try {
    const response = await fetch("/api/auth/me", {credentials: "same-origin", cache: "no-store"});
    if (response.status === 401) { window.location.replace("/login?expired=1"); return; }
    if (!response.ok) throw new Error("Unable to load your account.");
    const data = await response.json();
    csrfToken = data.csrf_token;
    document.getElementById("user-name").textContent = data.user.name;
    document.getElementById("user-email").textContent = data.user.email;
    document.getElementById("user-avatar").textContent = data.user.name.trim().split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
    sessionReady = true;
    nextButton.disabled = false; goButton.disabled = false;
    statusText.textContent = "";
    showStep(currentStep, false);
  } catch (error) {
    statusText.textContent = "We couldn't load your account. Refresh the page to try again.";
  }
}
logoutButton.addEventListener("click", async () => {
  if (!csrfToken) { window.location.reload(); return; }
  logoutButton.disabled = true;
  const errorBox = document.getElementById("session-error");
  errorBox.hidden = true;
  try {
    const response = await fetch("/api/auth/logout", {method: "POST", credentials: "same-origin", headers: {"X-CSRF-Token": csrfToken}});
    if (!response.ok && response.status !== 401) throw new Error("Sign out failed.");
    window.location.replace("/login?signed_out=1");
  } catch (error) {
    errorBox.textContent = "We couldn't sign you out. Check your connection and try again.";
    errorBox.hidden = false;
    logoutButton.disabled = false;
  }
});
form.addEventListener("input", () => {
  const results = document.getElementById("out");
  if (results.children.length) {
    results.replaceChildren();
    statusText.textContent = "Your answers have changed. Get a new recommendation when you're ready.";
  }
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (busy || !sessionReady) return;
  if (currentStep < steps.length - 1) { nextButton.click(); return; }
  for (let i = 0; i < steps.length; i++) if (!validateStep(i)) return;
  const data = new FormData(form), questionnaire = {}, preferences = {};
  for (const [key, value] of data.entries()) {
    if (PREF.includes(key)) {
      if (key === "risk_tolerance") preferences[key] = value;
      else if (value !== "") preferences[key] = Number(value);
    } else if (BOOL.includes(key)) questionnaire[key] = value === "true";
    else if (NUM.includes(key)) questionnaire[key] = Number(value);
    else questionnaire[key] = value;
  }
  busy = true;
  goButton.disabled = true; backButton.disabled = true;
  stepLinks.forEach(link => { link.disabled = true; });
  form.setAttribute("aria-busy", "true");
  // Freeze answers so the visible form continues to describe this request.
  form.querySelectorAll("input, select").forEach(input => { input.disabled = true; });
  goButton.textContent = "Building your assessment...";
  statusText.textContent = "Estimating your health profile and simulating 20,000 possible futures...";
  document.getElementById("out").replaceChildren();
  try {
    const response = await fetch("/api/recommend", {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
      body: JSON.stringify({questionnaire, preferences}),
    });
    if (response.status === 401) { window.location.replace("/login?expired=1"); return; }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === "string" ? data.detail : response.status === 422 ? "Please check your answers and try again." : "We couldn't generate your assessment. Please try again.");
    }
    await response.json();
    window.location.assign("/home");
  } catch (error) {
    const card = document.createElement("section");
    card.className = "notice error-notice";
    card.setAttribute("role", "alert");
    card.textContent = error instanceof TypeError ? "We couldn't reach the server. Check your connection and try again." : error.message;
    document.getElementById("out").replaceChildren(card);
    statusText.textContent = "Your answers are still here. You can try again.";
  } finally {
    busy = false;
    goButton.disabled = false; backButton.disabled = false;
    goButton.textContent = "Get my recommendation";
    form.setAttribute("aria-busy", "false");
    form.querySelectorAll("input, select").forEach(input => { input.disabled = false; });
    showStep(currentStep, false);
  }
});
window.addEventListener("pageshow", (event) => { if (event.persisted) window.location.reload(); });
loadSession();

