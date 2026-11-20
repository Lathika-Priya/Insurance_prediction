"use strict";
const money = value => "₹" + Number(value).toLocaleString("en-IN");
let plans = [], users = [], editingId = null, resetId = null;
const riskLabels = {highest:"Highest condition probability", diabetes:"Diabetes or prediabetes", high_bp:"High blood pressure", high_chol:"High cholesterol", heart_disease:"Heart disease", stroke:"Stroke", kidney_disease:"Kidney disease"};
const fields = [
 ["risk_condition","Risk measure for eligibility","select"],
 ["min_risk_pct","Minimum assessed risk (%)","number",0,100],
 ["max_risk_pct","Maximum assessed risk (%)","number",0,100],
 ["plan_id","Plan ID","text"], ["plan_name","Plan name","text"], ["plan_type","Plan type","select"],
 ["sum_insured","Sum insured (INR)","number",1,100000000],
 ["base_premium_inr","Base annual premium (INR)","number",1,10000000],
 ["min_entry_age","Minimum entry age","number",18,90],
 ["max_entry_age","Maximum entry age","number",18,90],
 ["copay_pct","Co-pay (%)","number",0,100],
 ["deductible_inr","Deductible (INR)","number",0,100000000],
 ["ped_wait_years","Pre-existing disease wait (years)","number",0,10],
 ["ped_premium_loading_pct","Pre-existing disease premium loading (%)","number",0,300],
 ["cardiac_sublimit_inr","Cardiac limit (INR; 0 = no limit)","number",0,100000000],
 ["opd_cover_inr","Annual outpatient cover (INR)","number",0,10000000],
 ["room_rent_capped","Room rent capped","checkbox"],
 ["active","Active in new assessments","checkbox"], ["description","Description","textarea"]
];
const ruleFields = [
 ["smoker_premium_loading_pct","Smoker premium loading (%)","number",0,300],
 ["room_rent_cap_proportionate_deduction_pct","Room rent claim deduction (%)","number",0,100],
 ["gst_pct","Tax on premium (%)","number",0,100]
];
function addField(parent, [name, title, type, min, max], value) {
  const label = document.createElement("label"); label.textContent = title;
  let input = document.createElement(type === "textarea" ? "textarea" : type === "select" ? "select" : "input");
  input.name = name; input.id = "field-" + name;
  if (type === "select") for (const item of (name === "risk_condition" ? Object.keys(riskLabels) : ["base","chronic","senior","topup"])) {
    const option = document.createElement("option"); option.value = item; option.textContent = name === "risk_condition" ? riskLabels[item] : item; input.append(option);
  }
  if (!["select","textarea"].includes(type)) input.type = type;
  if (type === "checkbox") { input.checked = Boolean(value); label.className = "checkbox-label"; }
  else {
    input.value = value ?? ""; input.required = true;
    if (type === "number") { input.min = min; input.max = max; input.step = ["sum_insured","min_entry_age","max_entry_age","ped_wait_years"].includes(name) ? "1" : "0.01"; }
    if (name === "plan_id") { input.pattern = "[A-Za-z0-9_-]{1,32}"; input.maxLength = 32; }
    if (name === "plan_name") { input.minLength = 2; input.maxLength = 120; }
    if (type === "textarea") { input.minLength = 2; input.maxLength = 1000; input.rows = 3; label.className = "full-field"; }
  }
  label.append(input); parent.append(label);
}
function renderPlans() {
  const body = document.getElementById("plans-body"); body.replaceChildren();
  for (const plan of plans) {
    const row = document.createElement("tr");
    for (const value of [plan.plan_name, plan.plan_type, money(plan.sum_insured), money(plan.base_premium_inr), riskLabels[plan.risk_condition] + ": " + plan.min_risk_pct + "-" + plan.max_risk_pct + "%", plan.active ? "Active" : "Inactive"]) {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }
    const cell = document.createElement("td"), button = document.createElement("button");
    button.type = "button"; button.className = "button ghost"; button.textContent = "Edit";
    button.setAttribute("aria-label", "Edit " + plan.plan_name);
    button.addEventListener("click", () => openPlan(plan)); cell.append(button); row.append(cell); body.append(row);
  }
}
function ageBands(parent, bands) {
  parent.replaceChildren();
  bands.forEach((band, index) => {
    const row = document.createElement("div"); row.className = "age-band";
    ["From age","Through age","Multiplier"].forEach((title, i) => {
      const label = document.createElement("label"); label.textContent = title;
      const input = document.createElement("input"); input.type = "number"; input.required = true;
      input.min = i === 2 ? "0.01" : "18"; input.max = i === 2 ? "20" : "120";
      input.step = i === 2 ? "0.01" : "1"; input.value = band[i]; input.setAttribute("aria-label", title + " for band " + (index + 1));
      label.append(input); row.append(label);
    }); parent.append(row);
  });
}
function populateRules(rules) {
  const container = document.getElementById("rule-fields"); container.replaceChildren();
  ruleFields.forEach(field => addField(container, field, rules[field[0]]));
  ageBands(document.getElementById("standard-bands"), rules.premium_age_factors);
  ageBands(document.getElementById("senior-bands"), rules.senior_plan_age_factors);
}
async function refresh() {
  const overview = await api("/api/admin/overview");
  plans = overview.plans;
  document.getElementById("count-plans").textContent = overview.active_plans;
  document.getElementById("count-users").textContent = overview.users;
  document.getElementById("count-assessments").textContent = overview.assessments;
  renderPlans(); populateRules(overview.rules);
  users = await api("/api/admin/users"); renderUsers();
}
function openPlan(plan = null) {
  editingId = plan?.plan_id || null;
  const defaults = {risk_condition:"highest", min_risk_pct:0, max_risk_pct:100, plan_id:"", plan_name:"", plan_type:"base", sum_insured:500000, base_premium_inr:10000,
    min_entry_age:18, max_entry_age:65, copay_pct:0, deductible_inr:0, ped_wait_years:3,
    ped_premium_loading_pct:0, cardiac_sublimit_inr:0, opd_cover_inr:0, room_rent_capped:false, active:true, description:""};
  const data = {...defaults, ...plan};
  const container = document.getElementById("plan-fields"); container.replaceChildren();
  fields.forEach(field => addField(container, field, data[field[0]]));
  document.getElementById("field-plan_id").readOnly = Boolean(editingId);
  document.getElementById("plan-title").textContent = editingId ? "Edit " + plan.plan_name : "Add sample plan";
  document.getElementById("plan-error").hidden = true;
  document.getElementById("plan-dialog").showModal();
}
document.getElementById("add-plan").addEventListener("click", () => openPlan());
document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));
document.querySelectorAll("[data-panel]").forEach(button => button.addEventListener("click", () => {
  for (const tab of document.querySelectorAll("[data-panel]")) {
    const selected = button === tab;
    document.getElementById(tab.dataset.panel).hidden = !selected;
    tab.classList.toggle("primary", selected); tab.classList.toggle("secondary", !selected);
    tab.setAttribute("aria-pressed", String(selected));
  }
}));
document.getElementById("plan-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('[type="submit"]');
  if (!form.reportValidity()) return;
  const payload = {};
  for (const [name,,type] of fields) {
    const input = form.elements[name];
    payload[name] = type === "checkbox" ? input.checked : type === "number" ? Number(input.value) : input.value;
  }
  button.disabled = true;
  try {
    await api(editingId ? "/api/admin/plans/" + encodeURIComponent(editingId) : "/api/admin/plans", {method: editingId ? "PUT" : "POST", body: JSON.stringify(payload)});
    document.getElementById("plan-dialog").close();
    showNotice("Plan saved. New assessments will use this configuration.");
    await refresh();
  } catch (error) {
    const box = document.getElementById("plan-error"); box.textContent = error.message; box.hidden = false;
    if (!document.getElementById("plan-dialog").open) showNotice(error.message, true);
  } finally { button.disabled = false; }
});
document.getElementById("rules-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector("button");
  if (!form.reportValidity()) return;
  const data = Object.fromEntries([...new FormData(form)].map(([key,value]) => [key,Number(value)]));
  const bands = id => [...document.querySelectorAll("#" + id + " .age-band")].map(row => [...row.querySelectorAll("input")].map(input => Number(input.value)));
  data.premium_age_factors = bands("standard-bands"); data.senior_plan_age_factors = bands("senior-bands");
  button.disabled = true;
  try { await api("/api/admin/rules", {method:"PUT", body:JSON.stringify(data)}); showNotice("Pricing rules saved for new assessments."); }
  catch(error) { showNotice(error.message, true); }
  finally { button.disabled = false; }
});
function renderUsers() {
  const query = document.getElementById("user-search").value.toLowerCase();
  const body = document.getElementById("users-body"); body.replaceChildren();
  for (const user of users.filter(user => (user.name + " " + user.email).toLowerCase().includes(query))) {
    const row = document.createElement("tr");
    for (const value of [user.name + " · " + user.email, user.role, new Date(user.created_at*1000).toLocaleDateString(), user.last_assessment_at ? "Completed" : "Not taken"]) {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    }
    const cell = document.createElement("td");
    if (user.role !== "admin") {
      const button = document.createElement("button"); button.className = "button ghost"; button.textContent = "Reset password";
      button.addEventListener("click", () => {
        resetId = user.id; document.getElementById("reset-form").reset();
        document.getElementById("reset-confirm").setCustomValidity("");
        document.getElementById("reset-target").textContent = user.name + " (" + user.email + ")";
        document.getElementById("reset-error").hidden = true; document.getElementById("reset-dialog").showModal();
      }); cell.append(button);
    } else cell.textContent = "Own profile";
    row.append(cell); body.append(row);
  }
  if (!body.children.length) { const row = body.insertRow(); const cell = row.insertCell(); cell.colSpan = 5; cell.textContent = "No accounts match your search."; }
}
document.getElementById("user-search").addEventListener("input", renderUsers);
const resetForm = document.getElementById("reset-form"), confirmReset = document.getElementById("reset-confirm");
resetForm.addEventListener("input", () => confirmReset.setCustomValidity(confirmReset.value === document.getElementById("reset-password").value ? "" : "Passwords do not match."));
resetForm.addEventListener("submit", async event => {
  event.preventDefault(); if (!resetForm.reportValidity()) return;
  const button = resetForm.querySelector('[type="submit"]'); button.disabled = true;
  try {
    await api("/api/admin/users/" + resetId + "/password", {method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(resetForm)))});
    resetForm.reset(); document.getElementById("reset-dialog").close(); showNotice("User password reset. Their existing sessions have been signed out.");
  } catch (error) { const box = document.getElementById("reset-error"); box.textContent = error.message; box.hidden = false; }
  finally { button.disabled = false; }
});
(async () => {
  try { await accountReady; await refresh(); document.getElementById("add-plan").disabled = false; document.querySelector("#rules-form button").disabled = false; }
  catch (error) { showNotice(error.message, true); }
})();
