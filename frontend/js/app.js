import {
  bulkDeleteApplications,
  clearApplications,
  clearStoredJobs,
  createApplication,
  deleteApplication,
  deleteStoredJob,
  fetchApplications,
  fetchResumes,
  searchJobs,
  setActiveResume,
  updateApplicationStatus,
  uploadResume,
} from "./api.js";
import { initCoverLetterModal } from "./components/coverLetterModal.js";
import { renderJobResults } from "./components/jobSearch.js";
import { initKanban, renderApplications } from "./components/kanbanBoard.js";
import { renderResumes } from "./components/resumeUpload.js";
import { ensureAuthenticated, wireLogout } from "./authSession.js";
import { selectedSources, selectedValuesByName, showToast } from "./utils.js";

const state = {
  resumes: [],
  applications: [],
  lastSearchKey: "",
  latestJobs: [],
  lastJobs: [],
  lastScores: {},
  selectedApplicationIds: new Set(),
};

const resumeUploadForm = document.getElementById("resume-upload-form");
const resumeFileInput = document.getElementById("resume-file");
const activeResumeSelect = document.getElementById("active-resume");
const resumeList = document.getElementById("resume-list");
const searchForm = document.getElementById("job-search-form");
const jobResults = document.getElementById("job-results");
const searchMeta = document.getElementById("search-meta");
const sourceBreakdown = document.getElementById("source-breakdown");
const clearSearchResultsBtn = document.getElementById("clear-search-results");
const clearStoredJobsDashboardBtn = document.getElementById("clear-stored-jobs-dashboard");
const refreshAppsBtn = document.getElementById("refresh-apps");
const deleteSelectedAppsBtn = document.getElementById("delete-selected-apps");
const clearAllAppsBtn = document.getElementById("clear-all-apps");
const appsSelectionMeta = document.getElementById("apps-selection-meta");
const searchSubmitBtn = document.getElementById("search-submit-btn");
const statJobs = document.getElementById("stat-jobs");
const statMatch = document.getElementById("stat-match");
const statApps = document.getElementById("stat-apps");
const laneCounts = {
  to_apply: document.getElementById("count-to_apply"),
  applied: document.getElementById("count-applied"),
  interviewing: document.getElementById("count-interviewing"),
  rejected: document.getElementById("count-rejected"),
  accepted: document.getElementById("count-accepted"),
};

const coverLetterModal = initCoverLetterModal(() => Number(activeResumeSelect.value));

async function loadResumes() {
  state.resumes = await fetchResumes();
  renderResumes(state.resumes, activeResumeSelect, resumeList);
}

async function loadApplications() {
  state.applications = await fetchApplications();
  reconcileApplicationSelection();
  renderApplications(state.applications, {
    selectedIds: state.selectedApplicationIds,
    onToggleSelect: (appId, checked) => {
      if (checked) {
        state.selectedApplicationIds.add(appId);
      } else {
        state.selectedApplicationIds.delete(appId);
      }
      updateApplicationSelectionUI();
    },
    onDelete: async (appId) => {
      await deleteSingleApplication(appId);
    },
  });
  updateApplicationSelectionUI();
  updateStats(getCurrentResultSet(), state.lastScores, state.applications);
}

resumeUploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const [file] = resumeFileInput.files;
  if (!file) {
    showToast("Choose a resume file first.");
    return;
  }

  try {
    await uploadResume(file);
    resumeFileInput.value = "";
    await loadResumes();
    showToast("Resume uploaded.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Upload failed.");
  }
});

activeResumeSelect.addEventListener("change", async () => {
  const resumeId = Number(activeResumeSelect.value);
  if (!resumeId) return;
  try {
    await setActiveResume(resumeId, true);
    await loadResumes();
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to set active resume.");
  }
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const resumeId = Number(activeResumeSelect.value);
  const resultMode = getResultMode();
  const matchMinInput = document.getElementById("match-min").value.trim();
  const matchMaxInput = document.getElementById("match-max").value.trim();
  const matchMinRaw = matchMinInput === "" ? Number.NaN : Number(matchMinInput);
  const matchMaxRaw = matchMaxInput === "" ? Number.NaN : Number(matchMaxInput);
  const matchMin = Number.isFinite(matchMinRaw) && matchMinRaw >= 0 ? Math.min(100, Math.max(0, matchMinRaw)) : null;
  const matchMax = Number.isFinite(matchMaxRaw) && matchMaxRaw >= 0 ? Math.min(100, Math.max(0, matchMaxRaw)) : null;
  const relevancy = selectedValuesByName("relevancy");
  const workMode = selectedValuesByName("work-mode");
  const experienceLevel = selectedValuesByName("experience-level");
  const payload = {
    keywords: document.getElementById("keywords").value,
    location: document.getElementById("location").value,
    resume_id: resumeId || null,
    filters: {
      salary_min: Number(document.getElementById("salary-min").value) || null,
      location_contains: document.getElementById("filter-location").value.trim() || null,
      match_percentage_min: matchMin,
      match_percentage_max: matchMax,
      date_posted: document.getElementById("date-posted").value || null,
      experience_level: experienceLevel,
      remote: workMode,
      work_mode: workMode,
      relevancy,
    },
    sources: selectedSources(),
  };

  if ((matchMin !== null || matchMax !== null || relevancy.length > 0) && !payload.resume_id) {
    showToast("Select an active resume to use match/relevancy filters.");
    return;
  }
  if (matchMin !== null && matchMax !== null && matchMin > matchMax) {
    payload.filters.match_percentage_min = matchMax;
    payload.filters.match_percentage_max = matchMin;
  }
  if (!payload.sources.length) {
    showToast("Select at least one source.");
    return;
  }
  const searchKey = JSON.stringify({
    keywords: payload.keywords,
    location: payload.location,
    filters: payload.filters,
    sources: payload.sources,
    resultMode,
  });

  try {
    setSearchLoading(true);
    searchMeta.textContent = "Searching...";
    const result = await searchJobs(payload);
    if (result.jobs.length === 0 && state.lastJobs.length > 0 && resultMode === "session") {
      const fallbackCount = resultMode === "latest" ? state.latestJobs.length : state.lastJobs.length;
      searchMeta.textContent = `No fresh jobs found. Keeping ${fallbackCount} jobs in current view.`;
      showToast("No new jobs found; kept previous results.");
      const visible = getCurrentResultSet();
      renderSourceBreakdown(visible);
      updateStats(visible, state.lastScores, state.applications);
      return;
    }

    state.lastSearchKey = searchKey;
    state.latestJobs = result.jobs;
    state.lastScores = { ...state.lastScores, ...(result.match_scores || {}) };
    state.lastJobs = mergeJobs(state.lastJobs, result.jobs);
    const visible = getCurrentResultSet();
    searchMeta.textContent =
      resultMode === "latest"
        ? `${visible.length} filtered jobs in latest search${result.cached ? " (cached)" : ""}.`
        : `${result.jobs.length} filtered jobs from latest search, ${state.lastJobs.length} total in session${result.cached ? " (cached)" : ""}.`;
    renderSourceBreakdown(visible);
    updateStats(visible, state.lastScores, state.applications);
    renderJobResults({
      jobs: visible,
      scores: state.lastScores,
      container: jobResults,
      onTrack: async (job) => {
        if (!resumeId) {
          showToast("Select an active resume before tracking applications.");
          return;
        }
        await createApplication({ resume_id: resumeId, job_id: job.id, status: "to_apply" });
        await loadApplications();
        showToast("Added to tracker.");
      },
      onCoverLetter: (job) => {
        if (!resumeId) {
          showToast("Select an active resume first.");
          return;
        }
        coverLetterModal.open(job.id);
      },
      onDelete: async (job) => {
        await deleteJobFromAllViews(job.id);
      },
    });
  } catch (error) {
    searchMeta.textContent = "";
    showToast(error.response?.data?.detail || "Search failed.");
  } finally {
    setSearchLoading(false);
  }
});

clearSearchResultsBtn.addEventListener("click", () => {
  state.lastSearchKey = "";
  state.latestJobs = [];
  state.lastJobs = [];
  state.lastScores = {};
  jobResults.innerHTML = "<p class=\"empty-state\">No jobs in this session. Run a fresh search to populate the board.</p>";
  sourceBreakdown.innerHTML = "";
  searchMeta.textContent = "Session results cleared.";
  updateStats([], {}, state.applications);
});

clearStoredJobsDashboardBtn.addEventListener("click", async () => {
  const ok = window.confirm("Clear all stored jobs for this account?");
  if (!ok) return;
  try {
    await clearStoredJobs();
    state.lastSearchKey = "";
    state.latestJobs = [];
    state.lastJobs = [];
    state.lastScores = {};
    jobResults.innerHTML = "<p class=\"empty-state\">All stored jobs were cleared. Run a new search to repopulate.</p>";
    sourceBreakdown.innerHTML = "";
    searchMeta.textContent = "Stored jobs cleared.";
    updateStats([], {}, state.applications);
    showToast("All stored jobs cleared.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to clear stored jobs.");
  }
});

refreshAppsBtn.addEventListener("click", loadApplications);

deleteSelectedAppsBtn.addEventListener("click", async () => {
  const selected = Array.from(state.selectedApplicationIds);
  if (!selected.length) return;
  const ok = window.confirm(`Delete ${selected.length} selected application(s)?`);
  if (!ok) return;
  try {
    await bulkDeleteApplications(selected);
    state.selectedApplicationIds.clear();
    await loadApplications();
    showToast("Selected applications deleted.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to delete selected applications.");
  }
});

clearAllAppsBtn.addEventListener("click", async () => {
  const ok = window.confirm("Clear all applications in tracker?");
  if (!ok) return;
  try {
    await clearApplications();
    state.selectedApplicationIds.clear();
    await loadApplications();
    showToast("All applications cleared.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to clear applications.");
  }
});

initKanban(async (appId, status) => {
  try {
    await updateApplicationStatus(appId, { status });
    await loadApplications();
    showToast("Application status updated.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to update status.");
  }
});

async function bootstrap() {
  try {
    const me = await ensureAuthenticated();
    if (!me) return;
    wireLogout("logout-btn");
    await Promise.all([loadResumes(), loadApplications()]);
  } catch (error) {
    showToast("Backend is not reachable yet.");
  }
}

bootstrap();

Array.from(document.querySelectorAll('input[name="result-mode"]')).forEach((node) => {
  node.addEventListener("change", () => {
    const visible = getCurrentResultSet();
    renderSourceBreakdown(visible);
    renderJobResults({
      jobs: visible,
      scores: state.lastScores,
      container: jobResults,
      onTrack: async (job) => {
        const resumeId = Number(activeResumeSelect.value);
        if (!resumeId) {
          showToast("Select an active resume before tracking applications.");
          return;
        }
        await createApplication({ resume_id: resumeId, job_id: job.id, status: "to_apply" });
        await loadApplications();
        showToast("Added to tracker.");
      },
      onCoverLetter: (job) => {
        const resumeId = Number(activeResumeSelect.value);
        if (!resumeId) {
          showToast("Select an active resume first.");
          return;
        }
        coverLetterModal.open(job.id);
      },
      onDelete: async (job) => {
        await deleteJobFromAllViews(job.id);
      },
    });
    updateStats(visible, state.lastScores, state.applications);
  });
});

function mergeJobs(existing, incoming) {
  const byId = new Map(existing.map((job) => [job.id, job]));
  incoming.forEach((job) => byId.set(job.id, job));
  return Array.from(byId.values());
}

async function deleteSingleApplication(appId) {
  const ok = window.confirm("Delete this application?");
  if (!ok) return;
  try {
    await deleteApplication(appId);
    state.selectedApplicationIds.delete(appId);
    await loadApplications();
    showToast("Application deleted.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to delete application.");
  }
}

function reconcileApplicationSelection() {
  const validIds = new Set(state.applications.map((app) => app.id));
  state.selectedApplicationIds = new Set(
    Array.from(state.selectedApplicationIds).filter((id) => validIds.has(id)),
  );
}

function updateApplicationSelectionUI() {
  const count = state.selectedApplicationIds.size;
  deleteSelectedAppsBtn.disabled = count === 0;
  clearAllAppsBtn.disabled = state.applications.length === 0;
  appsSelectionMeta.textContent = count > 0 ? `${count} selected` : "No applications selected.";
}

async function deleteJobFromAllViews(jobId) {
  const ok = window.confirm("Delete this job from your stored jobs?");
  if (!ok) return;
  try {
    await deleteStoredJob(jobId);
    state.latestJobs = state.latestJobs.filter((job) => job.id !== jobId);
    state.lastJobs = state.lastJobs.filter((job) => job.id !== jobId);
    delete state.lastScores[String(jobId)];
    const visible = getCurrentResultSet();
    renderSourceBreakdown(visible);
    renderJobResults({
      jobs: visible,
      scores: state.lastScores,
      container: jobResults,
      onTrack: async (job) => {
        const resumeId = Number(activeResumeSelect.value);
        if (!resumeId) {
          showToast("Select an active resume before tracking applications.");
          return;
        }
        await createApplication({ resume_id: resumeId, job_id: job.id, status: "to_apply" });
        await loadApplications();
        showToast("Added to tracker.");
      },
      onCoverLetter: (job) => {
        const resumeId = Number(activeResumeSelect.value);
        if (!resumeId) {
          showToast("Select an active resume first.");
          return;
        }
        coverLetterModal.open(job.id);
      },
      onDelete: async (job) => {
        await deleteJobFromAllViews(job.id);
      },
    });
    updateStats(visible, state.lastScores, state.applications);
    showToast("Job deleted.");
  } catch (error) {
    showToast(error.response?.data?.detail || "Failed to delete job.");
  }
}

function renderSourceBreakdown(jobs) {
  const counts = jobs.reduce((acc, job) => {
    const key = (job.source || "unknown").toLowerCase();
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  sourceBreakdown.innerHTML = "";
  Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .forEach(([source, count]) => {
      const chip = document.createElement("span");
      chip.className = "source-pill";
      chip.textContent = `${source}: ${count}`;
      sourceBreakdown.appendChild(chip);
    });
}

function getResultMode() {
  return document.querySelector('input[name="result-mode"]:checked')?.value || "session";
}

function getCurrentResultSet() {
  return getResultMode() === "latest" ? state.latestJobs : state.lastJobs;
}

function updateStats(jobs, scores, applications) {
  statJobs.textContent = String(jobs.length || 0);
  const scored = jobs
    .map((job) => scores?.[String(job.id)]?.score)
    .filter((score) => typeof score === "number");
  const avg = scored.length ? Math.round((scored.reduce((a, b) => a + b, 0) / scored.length) * 100) : 0;
  statMatch.textContent = `${avg}%`;
  statApps.textContent = String(applications.length || 0);

  const counts = {
    to_apply: 0,
    applied: 0,
    interviewing: 0,
    rejected: 0,
    accepted: 0,
  };
  applications.forEach((app) => {
    if (Object.prototype.hasOwnProperty.call(counts, app.status)) {
      counts[app.status] += 1;
    }
  });
  Object.entries(laneCounts).forEach(([status, node]) => {
    if (node) node.textContent = String(counts[status] || 0);
  });
}

function setSearchLoading(isLoading) {
  searchSubmitBtn.disabled = isLoading;
  searchSubmitBtn.textContent = isLoading ? "Searching..." : "Search Jobs";
}
