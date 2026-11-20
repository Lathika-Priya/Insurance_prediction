"use strict";
const inr = v => "₹" + Math.round(v).toLocaleString("en-IN");
const pct = v => (100 * v).toFixed(v < 0.1 ? 1 : 0) + "%";
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));


function render(d, scroll = true) {
  const c = d.risk.conditions;
  let html = `<div class="results-heading"><span class="eyebrow">YOUR PERSONAL ASSESSMENT</span><h2>A clearer view of what comes next.</h2><p>Explore your health profile and compare the sample plans below.</p></div><section class="card"><h2>Your health risk profile</h2>
    <p class="muted">BMI ${esc(d.risk.bmi)}. Estimated risks come from models trained on CDC BRFSS survey data (~570k people), calibrated and adjusted to Indian prevalence where data exists.</p>
    <div class="table-scroll" role="region" aria-label="Assessment comparison" tabindex="0"><table><tr><th scope="col">Condition</th><th scope="col">Status</th><th scope="col">Probability</th><th scope="col">Main modifiable drivers</th></tr>`;
  for (const k in c) {
    const x = c[k];
    const tag = x.status === "declared" ? `<span class="tag declared">Declared (pre-existing)</span>`
                                        : `<span class="tag">Estimated${x.answered === "don't know" ? " (you didn't know)" : ""}</span>`;
    const drv = (x.drivers || []).slice(0, 3).map(d => `${esc(d.factor)} (+${esc(d.adds_percentage_points)} pts)`).join("<br>") || "<span class='muted'>—</span>";
    html += `<tr><td>${esc(x.label)}</td><td>${tag}</td>
      <td><span class="bar"><span style="width:${Math.max(0, Math.min(100, 100 * x.probability))}%"></span></span> ${pct(x.probability)}</td><td>${drv}</td></tr>`;
  }
  html += `</table></div></section>`;

  const s = d.summary, set = d.settings;
  html += `<section class="card"><h2>Your recommended coverage</h2>`;
  if (!s) {
    html += `<p class="error">No plan matches your health-risk eligibility, age, and coverage preferences. See the excluded plans below for details.</p>`;
  } else {
    html += `<p>Over ${set.horizon_years} ${set.horizon_years === 1 ? "year" : "years"}, your expected medical bills are <b>${inr(d.expected_medical_bills_total)}</b>.
      Without new insurance you'd expect to pay <b>${inr(s.expected_total_cost_no_new_insurance)}</b>, and in a bad case (worst 5% of futures) about <b>${inr(s.cvar95_total_cost_no_new_insurance)}</b>.</p>
      <p>Best fit: <b>${esc(s.best_plan)}</b>.` +
      (s.best_plan !== s.cheapest_premium_plan ? ` Compared with the cheapest plan (${esc(s.cheapest_premium_plan)}), it costs ${inr(s.best_vs_cheapest_extra_premium)} more in first-year premium but protects you better against expensive years.` : ` It is also the cheapest eligible plan.`) + `</p>
      <div class="plans">`;
    d.recommendations.forEach((r, i) => {
      html += `<div class="plan ${i === 0 ? "top" : ""}">${i === 0 ? '<span class="best-fit-label">BEST MATCH</span>' : '<span class="alternative-label">ALTERNATIVE</span>'}<h3>#${r.rank} ${esc(r.plan_name)}</h3>
        <div class="muted">${esc(r.description)}</div><br>
        <div class="kv">
          <span>First-year premium</span><b>${inr(r.premium_year1)}</b>
          <span>Sum insured</span><span>${inr(r.sum_insured)}</span>
          <span>Expected total cost (${set.horizon_years} yrs)</span><span>${inr(r.expected_total_cost)}</span>
          <span>Bad-case total cost (worst 5%)</span><span>${inr(r.cvar95_total_cost)}</span>
          <span>Expected out-of-pocket</span><span>${inr(r.expected_out_of_pocket)}</span>
        </div>
        ${r.risk_eligibility ? '<p class="plan-risk-match">' + esc(r.risk_eligibility.label) + ': ' + esc(r.risk_eligibility.assessed_pct) + '% | Accepted range: ' + esc(r.risk_eligibility.min_pct) + '-' + esc(r.risk_eligibility.max_pct) + '%</p>' : ""}
        ${r.notes.length ? "<ul>" + r.notes.map(n => `<li>${esc(n)}</li>`).join("") + "</ul>" : ""}</div>`;
    });
    html += `</div>`;
  }
  html += `</section>`;

  html += `<section class="card"><h2>Compare all eligible plans</h2>
    <p class="muted">Score = expected total cost + ${set.lambda} × (bad-case cost − expected cost). Lower is better. Total cost = premiums + out-of-pocket over ${set.horizon_years} ${set.horizon_years === 1 ? "year" : "years"}, from ${set.simulations.toLocaleString()} simulations.</p>
    <div class="table-scroll" role="region" aria-label="Assessment comparison" tabindex="0"><table><tr><th scope="col">#</th><th scope="col">Plan</th><th scope="col">Premium (yr 1)</th><th scope="col">Expected total</th><th scope="col">Bad case (worst 5%)</th><th scope="col">Score</th></tr>`;
  for (const r of d.all_eligible_plans)
    html += `<tr><td>${r.rank}</td><td>${esc(r.plan_name)}</td><td>${inr(r.premium_year1)}</td><td>${inr(r.expected_total_cost)}</td><td>${inr(r.cvar95_total_cost)}</td><td>${inr(r.score)}</td></tr>`;
  html += `</table></div>`;
  if (d.excluded_plans.length)
    html += `<p class="muted" style="margin-top:10px">Not eligible: ` + d.excluded_plans.map(x => `${esc(x.plan_name)} (${esc(x.reasons.join("; "))})`).join(", ") + `</p>`;
  html += `</section>`;
  document.getElementById("out").innerHTML = html;
  if (!scroll) return;
  document.getElementById("out").focus({preventScroll: true});
  document.getElementById("out").scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
}

