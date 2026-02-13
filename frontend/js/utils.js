export function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2200);
}

export function selectedSources() {
  return Array.from(document.querySelectorAll('input[name="source"]:checked')).map((node) => node.value);
}
