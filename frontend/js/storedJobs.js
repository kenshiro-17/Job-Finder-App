import { clearStoredJobs, deleteStoredJob, fetchStoredJobs } from "./api.js";
import { ensureAuthenticated, wireLogout } from "./authSession.js";
import { showToast } from "./utils.js";

const filterForm = document.getElementById("stored-jobs-filter");
const queryInput = document.getElementById("query");
const sourceSelect = document.getElementById("source");
const limitSelect = document.getElementById("limit");
const loadMoreBtn = document.getElementById("load-more");
const clearStoredBtn = document.getElementById("clear-stored-jobs");
const meta = document.getElementById("stored-meta");
const grid = document.getElementById("stored-grid");

const state = {
  offset: 0,
  total: 0,
  limit: Number(limitSelect.value),
  jobs: [],
};

filterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.offset = 0;
  state.jobs = [];
  state.limit = Number(limitSelect.value);
  await loadJobs(false);
});

loadMoreBtn.addEventListener("click", async () => {
  if (state.offset >= state.total) return;
  await loadJobs(true);
});

clearStoredBtn.addEventListener("click", async () => {
  const ok = window.confirm("Clear all your stored jobs from this account?");
  if (!ok) return;
  try {
    await clearStoredJobs();
    state.offset = 0;
    state.total = 0;
    state.jobs = [];
    renderJobs([]);
    meta.textContent = "Stored jobs cleared.";
    loadMoreBtn.disabled = true;
    showToast("Stored jobs cleared.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to clear jobs.");
  }
});

grid.addEventListener("click", async (event) => {
  const button = event.target.closest('[data-action="delete-job"]');
  if (!button) return;
  const jobId = Number(button.getAttribute("data-job-id"));
  if (!jobId) return;
  const ok = window.confirm("Delete this job from your stored list?");
  if (!ok) return;
  try {
    await deleteStoredJob(jobId);
    state.jobs = state.jobs.filter((job) => job.id !== jobId);
    state.total = Math.max(0, state.total - 1);
    renderJobs(state.jobs);
    meta.textContent = `${state.jobs.length} loaded of ${state.total} stored jobs.`;
    loadMoreBtn.disabled = state.offset >= state.total;
    showToast("Job deleted.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to delete job.");
  }
});

async function loadJobs(append) {
  try {
    const response = await fetchStoredJobs({
      q: queryInput.value.trim() || undefined,
      source: sourceSelect.value || undefined,
      limit: state.limit,
      offset: state.offset,
    });
    state.total = response.total || 0;
    state.offset += response.jobs.length;
    state.jobs = append ? state.jobs.concat(response.jobs) : response.jobs.slice();
    renderJobs(state.jobs);
    meta.textContent = `${state.jobs.length} loaded of ${state.total} stored jobs.`;
    loadMoreBtn.disabled = state.offset >= state.total;
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to load stored jobs.");
  }
}

function renderJobs(jobs) {
  if (!jobs.length) {
    grid.innerHTML = "<p class=\"empty-state\">No stored jobs matched your filters.</p>";
    return;
  }

  grid.innerHTML = jobs
    .map((job) => {
      const source = escapeHtml(job.source || "unknown");
      const title = escapeHtml(job.title || "Untitled role");
      const company = escapeHtml(job.company || "Unknown company");
      const location = escapeHtml(job.location || "Unknown location");
      const posted = escapeHtml(job.posted_date ? `Posted ${job.posted_date}` : "Posted recently");
      const freshness = formatFreshness(job.scraped_at);
      const externalId = escapeHtml(job.external_job_id || "-");
      const href = escapeHtml(job.url || "#");
      return `
        <article class="stored-card">
          <div class="head-row">
            <span class="source">${source}</span>
            <span class="job-ref">${externalId}</span>
          </div>
          <h3>${title}</h3>
          <p class="company">${company}</p>
          <p class="location"><span>${location}</span><span>${freshness || posted}</span></p>
          <a class="job-link" href="${href}" target="_blank" rel="noopener">Open job posting ↗</a>
          <div class="actions">
            <button type="button" class="danger-btn compact" data-action="delete-job" data-job-id="${job.id}">Delete Job</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function formatFreshness(scrapedAt) {
  if (!scrapedAt) return "";
  const parsed = new Date(scrapedAt);
  const ageMs = Date.now() - parsed.getTime();
  if (!Number.isFinite(ageMs) || ageMs < 0) return "";
  if (ageMs <= 60 * 60 * 1000) return "Fresh <1h";
  return "";
}

async function bootstrap() {
  const me = await ensureAuthenticated();
  if (!me) return;
  wireLogout("logout-btn");
  await loadJobs(false);
}

bootstrap();
