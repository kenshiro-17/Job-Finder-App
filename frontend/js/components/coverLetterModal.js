import { generateCoverLetter } from "../api.js";
import { showToast } from "../utils.js";

export function initCoverLetterModal(getResumeId) {
  const dialog = document.getElementById("cover-letter-modal");
  const form = document.getElementById("cover-letter-form");
  const closeBtn = document.getElementById("close-cover-letter");
  const output = document.getElementById("cover-letter-output");

  closeBtn.addEventListener("click", () => dialog.close());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const resumeId = getResumeId();
    const jobId = Number(document.getElementById("cover-letter-job-id").value);
    const tone = document.getElementById("tone").value;
    const customIntro = document.getElementById("custom-intro").value;

    if (!resumeId || !jobId) {
      showToast("Select an active resume and job first.");
      return;
    }

    try {
      const result = await generateCoverLetter({
        resume_id: resumeId,
        job_id: jobId,
        tone,
        custom_intro: customIntro,
      });
      output.textContent = result.cover_letter;
      showToast("Cover letter generated.");
    } catch (error) {
      showToast(error.response?.data?.detail || "Failed to generate cover letter.");
    }
  });

  return {
    open(jobId) {
      document.getElementById("cover-letter-job-id").value = String(jobId);
      output.textContent = "";
      dialog.showModal();
    },
  };
}
