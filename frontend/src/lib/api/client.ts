import type {
	AuthSettings,
	BrowserAuthStatus,
	PreflightResult,
	RunDetail,
	RunInput,
	RunSummary
} from '$lib/types/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(`${API_BASE}${path}`, {
		headers: {
			'Content-Type': 'application/json',
			...(init?.headers ?? {})
		},
		...init
	});

	if (!response.ok) {
		let message = 'Request failed.';
		try {
			const data = await response.json();
			if (Array.isArray(data.detail)) {
				// FastAPI returns validation errors as a list. Flatten them into one readable sentence.
				message = data.detail
					.map((item: { loc?: Array<string | number>; msg?: string }) => {
						const pathLabel = item.loc ? item.loc.slice(1).join('.') : 'request';
						return `${pathLabel}: ${item.msg ?? 'Invalid value.'}`;
					})
					.join(' ');
			} else {
				message = data.detail ?? message;
			}
		} catch {
			message = response.statusText || message;
		}
		throw new Error(message);
	}

	if (response.status === 204 || response.headers.get('content-length') === '0') {
		return undefined as T;
	}

	return response.json() as Promise<T>;
}

export const api = {
	getAuth: () => request<AuthSettings>('/api/settings/auth'),
	saveAuth: (projectId: string) =>
		request<AuthSettings>('/api/settings/auth', {
			method: 'PUT',
			body: JSON.stringify({
				project_id: projectId
			})
		}),
	getBrowserAuth: () => request<BrowserAuthStatus>('/api/settings/auth/browser'),
	startBrowserAuth: () =>
		request<BrowserAuthStatus>('/api/settings/auth/browser', {
			method: 'POST',
			body: JSON.stringify({})
		}),
	listRuns: () => request<RunSummary[]>('/api/runs'),
	createRun: (payload: RunInput) =>
		request<{ id: number; status: string }>('/api/runs', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),
	preflightRun: (payload: RunInput) =>
		request<PreflightResult>('/api/runs/preflight', {
			method: 'POST',
			body: JSON.stringify(payload)
		}),
	getRun: (runId: number) => request<RunDetail>(`/api/runs/${runId}`),
	deleteRun: (runId: number) =>
		request<void>(`/api/runs/${runId}`, {
			method: 'DELETE'
		}),
	retryRun: (runId: number) =>
		request<{ id: number; status: string }>(`/api/runs/${runId}/retry`, {
			method: 'POST'
		}),
	kmlUrl: (runId: number) => `${API_BASE}/api/runs/${runId}/export.kml`,
	pngUrl: (runId: number) => `${API_BASE}/api/runs/${runId}/export.png`
};
