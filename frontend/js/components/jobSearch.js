import { createJobCard } from "./jobCard.js";

export function renderJobResults({ jobs, scores, container, onTrack, onCoverLetter, onDelete }) {
  container.innerHTML = "";
  if (!jobs.length) {
    container.innerHTML = "<p class=\"empty-state\">No jobs found yet. Try broader keywords, nearby locations, or enabling all sources.</p>";
    return;
  }

  jobs.forEach((job) => {
    const score = scores?.[String(job.id)]?.score ?? null;
    container.appendChild(
      createJobCard({
        job,
        score,
        onTrack,
        onCoverLetter,
        onDelete,
      }),
    );
  });
}
