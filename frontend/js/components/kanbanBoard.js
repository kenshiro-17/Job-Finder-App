export function initKanban(onMove) {
  document.querySelectorAll(".kanban-list").forEach((list) => {
    new Sortable(list, {
      group: "applications",
      animation: 150,
      ghostClass: "sortable-ghost",
      onAdd: async (evt) => {
        const appId = Number(evt.item.dataset.appId);
        const status = evt.to.id;
        await onMove(appId, status);
      },
    });
  });
}

export function renderApplications(applications, options = {}) {
  const {
    selectedIds = new Set(),
    onToggleSelect = () => {},
    onDelete = () => {},
  } = options;

  document.querySelectorAll(".kanban-list").forEach((node) => {
    node.innerHTML = "";
  });

  applications.forEach((app) => {
    const column = document.getElementById(app.status) || document.getElementById("to_apply");
    const note = app.notes ? escapeHtml(app.notes) : "No notes";
    const appliedDate = app.applied_date ? `Applied: ${escapeHtml(app.applied_date)}` : "Applied: pending";
    const card = document.createElement("article");
    card.className = "app-card";
    card.dataset.appId = String(app.id);
    card.innerHTML = `
      <div class="app-card-top">
        <label class="app-select">
          <input type="checkbox" data-action="select" ${selectedIds.has(app.id) ? "checked" : ""} />
          <span>Select</span>
        </label>
        <button type="button" class="danger-btn compact" data-action="delete">Delete</button>
      </div>
      <h4>Job #${app.job_id}</h4>
      <p class="muted">Resume #${app.resume_id}</p>
      <p class="muted">${appliedDate}</p>
      <p class="muted">${note}</p>
    `;
    card.querySelector('[data-action="select"]').addEventListener("change", (event) => {
      onToggleSelect(app.id, Boolean(event.target.checked));
    });
    card.querySelector('[data-action="delete"]').addEventListener("click", () => {
      onDelete(app.id);
    });
    column.appendChild(card);
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
