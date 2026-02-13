const client = axios.create({
  baseURL: "/api",
  timeout: 45000,
});

client.interceptors.request.use((config) => {
  const token = window.localStorage.getItem("job_finder_token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && !window.location.pathname.endsWith("/login.html")) {
      window.localStorage.removeItem("job_finder_token");
      window.localStorage.removeItem("job_finder_username");
      window.location.href = "/login.html";
    }
    return Promise.reject(error);
  },
);

export async function registerUser(payload) {
  const { data } = await client.post("/auth/register", payload);
  return data;
}

export async function loginUser(payload) {
  const { data } = await client.post("/auth/login", payload);
  return data;
}

export async function fetchMe() {
  const { data } = await client.get("/auth/me");
  return data;
}

export async function uploadResume(file) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post("/resumes/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function fetchResumes() {
  const { data } = await client.get("/resumes");
  return data;
}

export async function setActiveResume(resumeId, isActive) {
  const { data } = await client.put(`/resumes/${resumeId}/set-active`, { is_active: isActive });
  return data;
}

export async function searchJobs(payload) {
  const { data } = await client.post("/jobs/search", payload);
  return data;
}

export async function fetchStoredJobs(params = {}) {
  const { data } = await client.get("/jobs", { params });
  return data;
}

export async function clearStoredJobs() {
  const { data } = await client.delete("/jobs/clear");
  return data;
}

export async function deleteStoredJob(jobId) {
  const { data } = await client.delete(`/jobs/${jobId}`);
  return data;
}

export async function createApplication(payload) {
  const { data } = await client.post("/applications", payload);
  return data;
}

export async function fetchApplications() {
  const { data } = await client.get("/applications");
  return data;
}

export async function deleteApplication(appId) {
  const { data } = await client.delete(`/applications/${appId}`);
  return data;
}

export async function bulkDeleteApplications(applicationIds) {
  const { data } = await client.post("/applications/bulk-delete", {
    application_ids: applicationIds,
  });
  return data;
}

export async function clearApplications() {
  const { data } = await client.delete("/applications/clear");
  return data;
}

export async function updateApplicationStatus(appId, payload) {
  const { data } = await client.patch(`/applications/${appId}/status`, payload);
  return data;
}

export async function generateCoverLetter(payload) {
  const { data } = await client.post("/cover-letters/generate", payload);
  return data;
}
