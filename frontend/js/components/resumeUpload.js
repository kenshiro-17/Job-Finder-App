export function renderResumes(resumes, activeSelect, listNode) {
  activeSelect.innerHTML = "";
  listNode.innerHTML = "";

  if (!resumes.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Upload a resume first";
    activeSelect.appendChild(option);
    return;
  }

  resumes.forEach((resume) => {
    const skills = resume.parsed_skills || [];
    const option = document.createElement("option");
    option.value = resume.id;
    option.textContent = `${resume.filename}${resume.is_active ? " (active)" : ""}`;
    option.selected = !!resume.is_active;
    activeSelect.appendChild(option);

    const li = document.createElement("li");
    li.className = "resume-item";
    li.innerHTML = `
      <div class="resume-meta-row">
        <h4>${escapeHtml(resume.filename)}</h4>
        ${resume.is_active ? '<span class="active-pill">Active</span>' : ""}
      </div>
      <p class="muted">Skills (${skills.length}): ${escapeHtml(skills.slice(0, 8).join(", ") || "No skills parsed")}</p>
    `;
    listNode.appendChild(li);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}
