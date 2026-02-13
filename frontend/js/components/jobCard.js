export function createJobCard({ job, score, onTrack, onCoverLetter, onDelete }) {
  const link = resolveJobLink(job);
  const scorePct = score !== null ? Math.round(score * 100) : null;
  const posted = formatPostedDate(job.posted_date, job.scraped_at);
  const workMode = formatWorkMode(job.remote_type);
  const experience = formatExperienceLevel(job.experience_level, job.title, job.description, job.requirements);
  const relevancy = scorePct !== null ? classifyRelevancy(scorePct) : "Unscored";
  const card = document.createElement("article");
  card.className = "job-card";
  card.innerHTML = `
    <div class="head-row">
      <span class="source">${escapeHtml(job.source || "source")}</span>
      <span class="job-ref">ID ${escapeHtml(String(job.id || "-"))}</span>
    </div>
    <h3>${escapeHtml(job.title || "Untitled role")}</h3>
    <p class="company">${escapeHtml(job.company || "Unknown company")}</p>
    <p class="location"><span>${escapeHtml(job.location || "Unknown location")}</span><span>${escapeHtml(posted)}</span></p>
    <div class="job-taxonomy">
      <span>${escapeHtml(workMode)}</span>
      <span>${escapeHtml(experience)}</span>
      <span>${escapeHtml(job.job_type || "full-time")}</span>
    </div>
    <p class="desc">${escapeHtml((job.description || "No description available from source.").slice(0, 240))}${job.description ? "..." : ""}</p>
    <p class="score">Match Score: ${scorePct !== null ? `${scorePct}%` : "N/A"} · ${escapeHtml(relevancy)}</p>
    <div class="score-meter"><div class="score-fill" style="width:${scorePct !== null ? scorePct : 0}%"></div></div>
    <a class="job-link" href="${link}" target="_blank" rel="noopener">Open job posting ↗</a>
    <div class="actions">
      <button type="button" data-action="track">Track Application</button>
      <button type="button" class="secondary" data-action="cover">Generate Cover Letter</button>
      <button type="button" class="danger-btn compact" data-action="delete">Delete Job</button>
    </div>
  `;

  card.querySelector('[data-action="track"]').addEventListener("click", () => onTrack(job));
  card.querySelector('[data-action="cover"]').addEventListener("click", () => onCoverLetter(job));
  card.querySelector('[data-action="delete"]').addEventListener("click", () => onDelete?.(job));
  return card;
}

function resolveJobLink(job) {
  const raw = (job.url || "").trim();
  if (raw.startsWith("http://") || raw.startsWith("https://")) {
    if (job.source === "stepstone" && !isValidStepstoneJobLink(raw, job.external_job_id)) {
      return stepstoneSearchLink(job);
    }
    if (job.source === "linkedin" && !isValidLinkedinJobLink(raw)) {
      return linkedinFallback(job, raw);
    }
    return raw;
  }

  if (job.source === "indeed" && job.external_job_id) {
    return `https://de.indeed.com/viewjob?jk=${encodeURIComponent(job.external_job_id)}`;
  }
  if (job.source === "stepstone") {
    return stepstoneSearchLink(job);
  }
  if (job.source === "linkedin") {
    return linkedinFallback(job, raw);
  }
  return "#";
}

function isValidStepstoneJobLink(link, externalId) {
  if (link.includes("/job/")) return true;
  if (link.includes("/stellenangebote")) return true;
  if (externalId && /^\d+$/.test(externalId) && link.includes(`/job/${externalId}`)) return true;
  return false;
}

function stepstoneSearchLink(job) {
  const title = encodeURIComponent(job.title || "");
  const location = encodeURIComponent(job.location || "");
  return `https://www.stepstone.de/jobs/${title}?where=${location}`;
}

function isValidLinkedinJobLink(link) {
  return /^https?:\/\/([a-z]{2}\.)?linkedin\.com\/jobs\/view\//i.test(link);
}

function linkedinFallback(job, rawUrl = "") {
  const fromRaw = extractLinkedInId(rawUrl);
  if (fromRaw) {
    return `https://www.linkedin.com/jobs/view/${fromRaw}/`;
  }
  if (job.external_job_id && /^\d+$/.test(job.external_job_id)) {
    return `https://www.linkedin.com/jobs/view/${job.external_job_id}/`;
  }
  const keywords = encodeURIComponent(job.title || "");
  const location = encodeURIComponent(job.location || "");
  return `https://www.linkedin.com/jobs/search/?keywords=${keywords}&location=${location}`;
}

function extractLinkedInId(url) {
  if (!url) return "";
  const direct = url.match(/\/jobs\/view\/(\d+)/i);
  if (direct) return direct[1];
  const slug = url.match(/\/jobs\/view\/[^/?#]*-(\d+)/i);
  if (slug) return slug[1];
  return "";
}

function formatPostedDate(postedDate, scrapedAt) {
  if (scrapedAt) {
    const scraped = new Date(scrapedAt);
    const ageMs = Date.now() - scraped.getTime();
    if (Number.isFinite(ageMs) && ageMs >= 0 && ageMs <= 60 * 60 * 1000) {
      return "Fresh <1h";
    }
  }
  if (!postedDate) return "Posted recently";
  return `Posted ${postedDate}`;
}

function formatWorkMode(mode) {
  const normalized = String(mode || "").toLowerCase();
  if (normalized.includes("remote")) return "Remote";
  if (normalized.includes("hybrid")) return "Hybrid";
  if (normalized.includes("onsite") || normalized.includes("on-site")) return "Onsite";
  return "Onsite";
}

function formatExperienceLevel(level, title, description, requirements) {
  const normalized = String(level || "").toLowerCase().trim();
  if (normalized) {
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }
  const haystack = `${title || ""} ${description || ""} ${requirements || ""}`.toLowerCase();
  if (/(intern|graduate|entry|trainee|praktikum)/.test(haystack)) return "Entry";
  if (/(junior|\bjr\b)/.test(haystack)) return "Junior";
  if (/(lead|principal|staff|head of)/.test(haystack)) return "Lead";
  if (/(senior|\bsr\b)/.test(haystack)) return "Senior";
  return "Mid";
}

function classifyRelevancy(scorePct) {
  if (scorePct >= 70) return "Strong Relevancy";
  if (scorePct >= 50) return "Good Relevancy";
  return "Possible Relevancy";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}
