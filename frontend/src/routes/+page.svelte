<script lang="ts">
	import '../app.css';

	import { onDestroy, onMount } from 'svelte';

	import { api } from '$lib/api/client';
	import AoiMap from '$lib/components/AoiMap.svelte';
	import ImageModal from '$lib/components/ImageModal.svelte';
	import StepRail from '$lib/components/StepRail.svelte';
	import TilePanel from '$lib/components/TilePanel.svelte';
	import type {
		AuthSettings,
		BrowserAuthStatus,
		PreflightResult,
		RunDetail,
		RunSummary
	} from '$lib/types/api';

	const steps = [
		{ id: 'auth', label: 'Authenticate', blurb: 'Save the Earth Engine project and sign in.' },
		{ id: 'aoi', label: 'Select AOI', blurb: 'Draw the footprint to inspect on the map.' },
		{ id: 'run', label: 'Run PWTT', blurb: 'Choose dates, thresholds, and launch the analysis.' },
		{ id: 'results', label: 'Review & Export', blurb: 'Inspect imagery, scan metrics, and download KML.' }
	];

	let currentStep = 0;
	let authState: AuthSettings | null = null;
	let browserAuth: BrowserAuthStatus | null = null;
	let recentRuns: RunSummary[] = [];
	let currentRun: RunDetail | null = null;
	let pollingHandle: ReturnType<typeof setInterval> | null = null;
	let browserAuthHandle: ReturnType<typeof setInterval> | null = null;
	let deletingRunId: number | null = null;
	let historyError = '';
	let imageViewer:
		| {
				title: string;
				imageUrl: string;
				showLegend: boolean;
		  }
		| null = null;

	let projectId = '';
	let authSaving = false;
	let authError = '';
	let authNotice = '';
	let initialStateLoaded = false;

	let aoiGeometry: GeoJSON.Geometry | null = null;
	let savedAoiGeometry: GeoJSON.Geometry | null = null;
	let aoiName = 'New AOI';
	let savedAoiName = 'New AOI';
	let aoiMessage = '';

	// Bounding-box area thresholds (km²) — kept in sync with backend schemas.py.
	const AOI_WARN_KM2 = 25_000;
	const AOI_MAX_KM2 = 250_000;

	function computeBboxAreaKm2(geometry: GeoJSON.Geometry | null): number {
		if (!geometry) return 0;
		const coords: [number, number][] = [];
		function collect(obj: unknown): void {
			if (Array.isArray(obj) && obj.length >= 2 && typeof obj[0] === 'number') {
				coords.push([obj[0] as number, obj[1] as number]);
			} else if (Array.isArray(obj)) {
				(obj as unknown[]).forEach(collect);
			} else if (obj && typeof obj === 'object') {
				Object.values(obj as Record<string, unknown>).forEach(collect);
			}
		}
		collect(geometry);
		if (coords.length < 3) return 0;
		const lons = coords.map((c) => c[0]);
		const lats = coords.map((c) => c[1]);
		const latSpan = Math.max(...lats) - Math.min(...lats);
		const lonSpan = Math.max(...lons) - Math.min(...lons);
		const avgLat = (Math.max(...lats) + Math.min(...lats)) / 2;
		const heightKm = latSpan * 111.32;
		const widthKm = lonSpan * 111.32 * Math.cos((avgLat * Math.PI) / 180);
		return Math.round(heightKm * widthKm);
	}

	let warStart = '2023-10-10';
	let inferenceStart = '2024-07-01';
	// Defaults follow Ballinger (2025): a 1-year baseline and a 2-month post
	// window. Users can shorten either; the advisories below explain the risk.
	let preIntervalInput = '12';
	let postIntervalInput = '2';
	let thresholdInput = '3.3';

	let runError = '';
	let runLoading = false;
	let coverageCheck: PreflightResult | null = null;
	let coverageChecking = false;
	let coverageSignature = '';
	let pollNow = Date.now();
	let runBlockers: string[] = [];
	let primaryRunBlocker = '';
	let hasSavedProject = false;
	let hasEarthEngineLogin = false;
	let authReady = false;
	let pwttLegend: Array<{ color: string; label: string }> = [];

	// SQLite timestamps are UTC but carry no timezone marker; normalize before parsing.
	function parseUtcDate(value: string): Date {
		if (/[zZ]|[+-]\d{2}:\d{2}$/.test(value)) {
			return new Date(value);
		}
		return new Date(`${value.replace(' ', 'T')}Z`);
	}

	function formatRunDate(value: string): string {
		const parsed = parseUtcDate(value);
		return Number.isNaN(parsed.getTime())
			? ''
			: parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
	}

	function elapsedMinutes(value: string, now: number): number {
		const started = parseUtcDate(value).getTime();
		if (Number.isNaN(started)) return 0;
		return Math.max(0, Math.round((now - started) / 60000));
	}

	// Accept either decimal style so people do not have to adjust to the browser's preferred format.
	function parseDecimalInput(rawValue: string) {
		const normalized = rawValue.trim().replace(',', '.');
		if (!normalized) {
			return Number.NaN;
		}

		return Number(normalized);
	}

	async function loadInitialState() {
		authState = await api.getAuth();
		browserAuth = await api.getBrowserAuth();
		recentRuns = await api.listRuns();
		projectId = authState.project_id ?? '';
		if (authState.project_id && !authState.configured) {
			authNotice = 'Project saved. Earth Engine login is still required before you can continue.';
		}
		if (authState.configured) {
			authNotice = 'Project saved and Earth Engine is ready.';
			currentStep = 1;
		}
		initialStateLoaded = true;
	}

	async function refreshAuthState() {
		authState = await api.getAuth();
		browserAuth = await api.getBrowserAuth();
	}

	async function saveAuth() {
		authSaving = true;
		authError = '';
		authNotice = '';
		try {
			authState = await api.saveAuth(projectId);
			browserAuth = await api.getBrowserAuth();
			if (authState.configured) {
				authNotice = `Project saved. Connected to ${authState.project_id}.`;
				currentStep = 1;
			} else {
				authNotice = 'Project saved. Earth Engine login is still required before you can continue.';
			}
		} catch (error) {
			authError = error instanceof Error ? error.message : 'Unable to save the Earth Engine project.';
		} finally {
			authSaving = false;
		}
	}

	async function startBrowserAuth() {
		authError = '';
		try {
			browserAuth = await api.startBrowserAuth();
			if (browserAuthHandle) {
				clearInterval(browserAuthHandle);
			}
			browserAuthHandle = setInterval(async () => {
				await refreshAuthState();
				if (browserAuth?.status !== 'running') {
					clearInterval(browserAuthHandle as ReturnType<typeof setInterval>);
					browserAuthHandle = null;
				}
			}, 2000);
		} catch (error) {
			authError = error instanceof Error ? error.message : 'Unable to start browser login.';
		}
	}

	function startPolling(runId: number) {
		if (pollingHandle) {
			clearInterval(pollingHandle);
		}

		pollingHandle = setInterval(async () => {
			pollNow = Date.now();
			currentRun = await api.getRun(runId);
			recentRuns = await api.listRuns();
			if (currentRun.status === 'completed' || currentRun.status === 'failed') {
				clearInterval(pollingHandle as ReturnType<typeof setInterval>);
				pollingHandle = null;
				currentStep = 3;
			}
		}, 3000);
	}

	function buildRunPayload() {
		return {
			aoi_name: savedAoiName,
			aoi_geojson: savedAoiGeometry as GeoJSON.Geometry,
			war_start: warStart,
			inference_start: inferenceStart,
			pre_interval: parseDecimalInput(preIntervalInput),
			post_interval: parseDecimalInput(postIntervalInput),
			threshold: parseDecimalInput(thresholdInput)
		};
	}

	async function checkCoverage(): Promise<PreflightResult | null> {
		if (!savedAoiGeometry) {
			runError = 'Save an AOI before checking imagery coverage.';
			return null;
		}

		coverageChecking = true;
		runError = '';
		try {
			coverageCheck = await api.preflightRun(buildRunPayload());
			coverageSignature = runSignature;
			return coverageCheck;
		} catch (error) {
			runError = error instanceof Error ? error.message : 'Unable to check imagery coverage.';
			return null;
		} finally {
			coverageChecking = false;
		}
	}

	async function submitRun() {
		if (!savedAoiGeometry) {
			runError = 'Save an AOI before starting the analysis.';
			return;
		}

		runLoading = true;
		runError = '';
		try {
			// Validate imagery coverage first: a bad date combination should fail
			// here in seconds, not after minutes in the processing queue.
			let preflight = coverageSignature === runSignature ? coverageCheck : null;
			if (!preflight) {
				preflight = await checkCoverage();
			}
			if (!preflight) {
				return;
			}
			if (!preflight.ok) {
				runError = preflight.message ?? 'No usable radar imagery was found for these dates.';
				return;
			}

			const created = await api.createRun(buildRunPayload());
			currentRun = await api.getRun(created.id);
			recentRuns = await api.listRuns();
			currentStep = 3;
			startPolling(created.id);
		} catch (error) {
			runError = error instanceof Error ? error.message : 'Unable to create the run.';
		} finally {
			runLoading = false;
		}
	}

	function reuseRunSettings(run: RunDetail) {
		const parameters = run.parameters;
		warStart = parameters.war_start;
		inferenceStart = parameters.inference_start;
		preIntervalInput = String(parameters.pre_interval);
		postIntervalInput = String(parameters.post_interval);
		thresholdInput = String(parameters.threshold);
		savedAoiGeometry = structuredClone(parameters.aoi_geojson);
		aoiGeometry = structuredClone(parameters.aoi_geojson);
		savedAoiName = run.aoi_name ?? 'Saved AOI';
		aoiName = savedAoiName;
		aoiMessage = 'AOI loaded from the previous run.';
		runError = '';
		currentStep = 2;
	}

	function saveAoi() {
		if (!aoiGeometry) {
			aoiMessage = 'Draw a polygon or rectangle first.';
			return;
		}

		savedAoiGeometry = structuredClone(aoiGeometry);
		savedAoiName = aoiName.trim() || 'Saved AOI';
		aoiName = savedAoiName;
		aoiMessage = 'AOI saved. You can run the analysis now.';
		currentStep = 2;
	}

	function buildRunBlockers() {
		const blockers: string[] = [];
		const conflictDate = new Date(warStart);
		const inferenceDate = new Date(inferenceStart);
		const preInterval = parseDecimalInput(preIntervalInput);
		const postInterval = parseDecimalInput(postIntervalInput);
		const threshold = parseDecimalInput(thresholdInput);
		const hasSavedProject = Boolean((authState?.project_id ?? projectId).trim());
		const hasEarthEngineLogin = Boolean(authState?.credentials_present);

		if (!initialStateLoaded) {
			return blockers;
		}

		if (!hasSavedProject) {
			blockers.push('Save the Earth Engine project in step 1.');
		}

		if (!hasEarthEngineLogin) {
			blockers.push('Complete the Earth Engine login in step 1.');
		}

		if (!savedAoiGeometry) {
			blockers.push('Save an AOI in step 2 before starting the analysis.');
		}

		if (savedAoiGeometry && aoiGeometry) {
			const saved = JSON.stringify(savedAoiGeometry);
			const draft = JSON.stringify(aoiGeometry);
			if (saved !== draft) {
				blockers.push('The AOI has changed. Save it again in step 2 to use the new shape.');
			}
		}

		if (savedAoiGeometry && savedAoiAreaKm2 > AOI_MAX_KM2) {
			blockers.push(
				`AOI bounding box is ~${savedAoiAreaKm2.toLocaleString()} km² — above the ${AOI_MAX_KM2.toLocaleString()} km² limit. Processing an area this large would take many hours. Draw a smaller area.`
			);
		}

		if (Number.isNaN(conflictDate.getTime())) {
			blockers.push('Choose a valid conflict start date.');
		}

		if (Number.isNaN(inferenceDate.getTime())) {
			blockers.push('Choose a valid inference start date.');
		}

		if (!Number.isNaN(conflictDate.getTime()) && !Number.isNaN(inferenceDate.getTime()) && inferenceDate < conflictDate) {
			blockers.push('Inference start must be on or after the conflict start date.');
		}

		if (!Number.isFinite(preInterval) || preInterval <= 0) {
			blockers.push('Pre-war months must be greater than 0.');
		}

		if (!Number.isFinite(postInterval) || postInterval <= 0) {
			blockers.push('Post-war months must be greater than 0.');
		}

		if (!Number.isFinite(threshold) || threshold <= 0) {
			blockers.push('Threshold must be greater than 0.');
		}

		return blockers;
	}

	function guideToRunRequirement() {
		const preInterval = parseDecimalInput(preIntervalInput);
		const postInterval = parseDecimalInput(postIntervalInput);
		const parsedThreshold = parseDecimalInput(thresholdInput);
		const conflictDate = new Date(warStart);
		const inferenceDate = new Date(inferenceStart);

		const hasSavedProject = Boolean((authState?.project_id ?? projectId).trim());
		const hasEarthEngineLogin = Boolean(authState?.credentials_present);

		if (!hasSavedProject || !hasEarthEngineLogin) {
			currentStep = 0;
			authError = !hasSavedProject
				? 'Save the Earth Engine project before starting the analysis.'
				: 'Complete the Earth Engine login before starting the analysis.';
			return;
		}

		if (!savedAoiGeometry) {
			currentStep = 1;
			aoiMessage = 'Draw an AOI and click "Save AOI" before starting the analysis.';
			return;
		}

		if (savedAoiGeometry && aoiGeometry) {
			const saved = JSON.stringify(savedAoiGeometry);
			const draft = JSON.stringify(aoiGeometry);
			if (saved !== draft) {
				currentStep = 1;
				aoiMessage = 'The AOI changed. Click "Save AOI" again to use the updated shape.';
				return;
			}
		}

		currentStep = 2;
		if (Number.isNaN(conflictDate.getTime())) {
			runError = 'Choose a valid conflict start date.';
			return;
		}

		if (Number.isNaN(inferenceDate.getTime())) {
			runError = 'Choose a valid inference start date.';
			return;
		}

		if (inferenceDate < conflictDate) {
			runError = 'Inference start must be on or after the conflict start date.';
			return;
		}

		if (!Number.isFinite(preInterval) || preInterval <= 0) {
			runError = 'Pre-war months must be greater than 0.';
			return;
		}

		if (!Number.isFinite(postInterval) || postInterval <= 0) {
			runError = 'Post-war months must be greater than 0.';
			return;
		}

		if (!Number.isFinite(parsedThreshold) || parsedThreshold <= 0) {
			runError = 'Threshold must be greater than 0.';
		}
	}

	function handleStartAnalysis() {
		runError = '';
		authError = '';
		if (runBlockers.length > 0) {
			guideToRunRequirement();
			return;
		}

		void submitRun();
	}

	async function openRun(runId: number) {
		currentRun = await api.getRun(runId);
		currentStep = 3;
		if (currentRun.status === 'queued' || currentRun.status === 'running') {
			startPolling(runId);
		}
	}

	function openImageViewer(config: {
		title: string;
		imageUrl: string;
		showLegend: boolean;
	}) {
		imageViewer = config;
	}

	function closeImageViewer() {
		imageViewer = null;
	}

	let retryingRunId: number | null = null;
	let retryError = '';

	async function retryRun(runId: number) {
		retryingRunId = runId;
		retryError = '';
		try {
			await api.retryRun(runId);
			currentRun = await api.getRun(runId);
			recentRuns = await api.listRuns();
			startPolling(runId);
		} catch (error) {
			retryError = error instanceof Error ? error.message : 'Unable to retry the run.';
		} finally {
			retryingRunId = null;
		}
	}

	async function removeRun(runId: number) {
		const target = recentRuns.find((run) => run.id === runId);
		const label = target?.aoi_name || `Run ${runId}`;
		if (!confirm(`Remove "${label}"? This deletes the run and its cached results permanently.`)) {
			return;
		}

		deletingRunId = runId;
		historyError = '';
		try {
			await api.deleteRun(runId);
			recentRuns = recentRuns.filter((run) => run.id !== runId);
			if (currentRun?.id === runId) {
				currentRun = null;
			}
		} catch (error) {
			historyError = error instanceof Error ? error.message : 'Unable to remove the run.';
		} finally {
			deletingRunId = null;
		}
	}

	onMount(() => {
		loadInitialState().catch((error) => {
			authError = error instanceof Error ? error.message : 'Unable to reach the backend.';
		});
	});

	onDestroy(() => {
		if (pollingHandle) {
			clearInterval(pollingHandle);
		}
		if (browserAuthHandle) {
			clearInterval(browserAuthHandle);
		}
	});

	$: aoiAreaKm2 = computeBboxAreaKm2(aoiGeometry);
	$: savedAoiAreaKm2 = computeBboxAreaKm2(savedAoiGeometry);
	$: runBlockers = buildRunBlockers();
	$: canStartRun = runBlockers.length === 0 && !runLoading;
	$: primaryRunBlocker = runBlockers[0] ?? '';
	$: hasSavedProject = Boolean((authState?.project_id ?? projectId).trim());
	$: hasEarthEngineLogin = Boolean(authState?.credentials_present);
	$: authReady = hasSavedProject && hasEarthEngineLogin;
	// A coverage result only applies to the exact AOI + dates it was checked for.
	$: runSignature = JSON.stringify([
		savedAoiGeometry,
		warStart,
		inferenceStart,
		preIntervalInput,
		postIntervalInput
	]);
	$: if (coverageCheck && coverageSignature !== runSignature) {
		coverageCheck = null;
	}
	// Soft advisories: unlike runBlockers these never stop the run — they explain
	// the statistical cost of the chosen windows so short windows stay possible.
	$: runAdvisories = (() => {
		const advisories: string[] = [];
		const preInterval = parseDecimalInput(preIntervalInput);
		const postInterval = parseDecimalInput(postIntervalInput);
		if (Number.isFinite(postInterval) && postInterval > 0 && postInterval < 2) {
			advisories.push(
				'Post-war window under 2 months: fewer radar images means noisier statistics and more false detections. ' +
					'The method was validated with 2-month windows — shorter windows are fine for a quick look, but treat the result as indicative.'
			);
		}
		if (Number.isFinite(preInterval) && preInterval > 0 && preInterval < 12) {
			advisories.push(
				'Baseline under 12 months: the baseline no longer averages over a full seasonal cycle, so snow, rain, and vegetation changes can be mistaken for damage.'
			);
		}
		return advisories;
	})();
	// Sample-size warnings from the coverage check. ~5 scenes per orbit is what
	// the method's validation used for its 2-month post windows.
	$: coverageWarnings = (() => {
		const coverage = coverageCheck?.coverage;
		if (!coverageCheck?.ok || !coverage) return [] as string[];
		const warnings: string[] = [];
		if (coverage.min_post_scenes_per_orbit < 4) {
			warnings.push(
				`Only ${coverage.min_post_scenes_per_orbit} post-war image${coverage.min_post_scenes_per_orbit === 1 ? '' : 's'} on the weakest orbit — expect noisy results. Widening the post-war window adds images.`
			);
		}
		if (coverage.min_pre_scenes_per_orbit < 10) {
			warnings.push(
				`Only ${coverage.min_pre_scenes_per_orbit} baseline images on the weakest orbit — the pre-war baseline may be unstable. Widening the pre-war window adds images.`
			);
		}
		return warnings;
	})();
	$: {
		const threshold = parseDecimalInput(thresholdInput);
		const base = Number.isFinite(threshold) ? threshold : 3.3;
		// The same cutoffs the building categories use (threshold, +0.75, +1.5),
		// so the map legend and the building chips always agree.
		pwttLegend = [
			{ color: '#f6d743', label: `Elevated (T ≥ ${+base.toFixed(2)})` },
			{ color: '#e85d04', label: `High (T ≥ ${+(base + 0.75).toFixed(2)})` },
			{ color: '#5f0f40', label: `Severe (T ≥ ${+(base + 1.5).toFixed(2)})` }
		];
	}
	$: if (aoiGeometry) {
		const saved = savedAoiGeometry ? JSON.stringify(savedAoiGeometry) : '';
		const draft = JSON.stringify(aoiGeometry);
		if (saved && saved !== draft) {
			aoiMessage = 'AOI changed. Save it again to use the new shape.';
		}
	}
</script>

<svelte:head>
	<title>PWTT Wizard</title>
	<meta
		name="description"
		content="A guided PWTT desktop-style interface for authentication, AOI selection, battle-damage analysis, and KML export."
	/>
</svelte:head>

<div class="page">
	<StepRail {steps} current={currentStep} />

	<main class="workspace">
		<section class="topbar">
			<div>
				<p class="eyebrow">PWTT Wizard</p>
				<h2>Set up authentication, choose an area, and run the analysis.</h2>
				<p class="copy subtle">Based on <a href="https://www.sciencedirect.com/science/article/pii/S0034425725004298" target="_blank" rel="noreferrer">Ballinger 2025</a></p>
			</div>
			<div class="status-grid">
				<div><span>Saved auth</span><strong>{authReady ? 'Ready' : hasSavedProject ? 'Login needed' : 'Missing'}</strong></div>
				<div>
					<span>AOI</span>
					<strong>{savedAoiGeometry ? 'Saved' : aoiGeometry ? 'Drawn' : 'Pending'}</strong>
				</div>
				<div><span>Latest run</span><strong>{currentRun?.status ?? 'Idle'}</strong></div>
			</div>
		</section>

		<div class="cards">
			<section class="card">
				<header>
					<span class="step-tag">Step 1</span>
					<h3>Authenticate and store access</h3>
				</header>
				<p class="copy">Save the Earth Engine project ID and confirm that this computer is signed in.</p>
				<div class="field-grid">
					<label>
						<span>Earth Engine project ID</span>
						<input bind:value={projectId} placeholder="my-earth-engine-project" />
					</label>
					<div class="credential-card">
						<span>Local credential file</span>
						<strong>{authState?.credentials_path ?? browserAuth?.credentials_path ?? 'Unavailable'}</strong>
						<small>{hasEarthEngineLogin ? 'Earth Engine login found.' : 'No local Earth Engine login yet.'}</small>
					</div>
				</div>
				<div class="actions">
					<button class="secondary" on:click={startBrowserAuth}>Open Earth Engine Login</button>
					<button class="primary" disabled={authSaving || !projectId.trim()} on:click={saveAuth}>
						{authSaving ? 'Saving...' : 'Save project'}
					</button>
				</div>
				{#if browserAuth}
					<p class:success={browserAuth.status === 'completed'} class:error={browserAuth.status === 'failed'}>
						{browserAuth.message}
					</p>
				{/if}
				{#if authNotice}
					<p class="success">{authNotice}</p>
				{/if}
				{#if hasSavedProject && !hasEarthEngineLogin}
					<p class="copy subtle">The project is saved, but Earth Engine login is still missing.</p>
				{/if}
				{#if authError}
					<p class="error">{authError}</p>
				{/if}
			</section>

			<section class="card">
				<header>
					<span class="step-tag">Step 2</span>
					<h3>Select the area of interest</h3>
				</header>
				<p class="copy">Draw one rectangle or polygon for the area you want to analyse.</p>
				<div class="field-grid compact">
					<label>
						<span>AOI name</span>
						<input bind:value={aoiName} placeholder="Southern Lebanon sector" />
					</label>
				</div>
				<AoiMap bind:value={aoiGeometry} />

				{#if aoiAreaKm2 > 0}
					<p
						class="aoi-size-hint"
						class:aoi-size-warn={aoiAreaKm2 > AOI_WARN_KM2 && aoiAreaKm2 <= AOI_MAX_KM2}
						class:aoi-size-block={aoiAreaKm2 > AOI_MAX_KM2}
					>
						{#if aoiAreaKm2 > AOI_MAX_KM2}
							⛔ Bounding box ~{aoiAreaKm2.toLocaleString()} km² — too large to process. Draw a smaller area.
						{:else if aoiAreaKm2 > AOI_WARN_KM2}
							⚠ Bounding box ~{aoiAreaKm2.toLocaleString()} km² — large area. The run will work but expect 30–90 min of
							processing. Elongated or diagonal shapes measure larger than they look because the size is taken from the
							surrounding rectangle.
						{:else}
							Bounding box ~{aoiAreaKm2.toLocaleString()} km²
						{/if}
					</p>
				{/if}

				<div class="actions">
					<button class="secondary" disabled={!authReady || !aoiGeometry} on:click={saveAoi}>
						Save AOI
					</button>
				</div>
				{#if aoiMessage}
					<p class:success={savedAoiGeometry !== null && aoiMessage.includes('saved')} class:error={aoiMessage.includes('Draw')}>
						{aoiMessage}
					</p>
				{/if}
			</section>

			<section class="card">
				<header>
					<span class="step-tag">Step 3</span>
					<h3>Run the PWTT pipeline</h3>
				</header>
				<p class="copy">Adjust dates and thresholds if needed, then start the run.</p>
					<div class="field-grid">
						<label>
							<span class="label-row">
								Conflict start
								<button
									type="button"
									class="info-chip"
									aria-label="The first date when conflict-related damage could begin. Images before this date are used as the baseline."
									data-tip="The first date when conflict-related damage could begin. Images before this date are used as the baseline."
								>
									i
								</button>
							</span>
							<input bind:value={warStart} type="date" />
						</label>
						<label>
							<span class="label-row">
								Inference start
								<button
									type="button"
									class="info-chip"
									aria-label="The first date of the post-event period you want to test. Use this to target the time window you want to measure."
									data-tip="The first date of the post-event period you want to test. Use this to target the time window you want to measure."
								>
									i
								</button>
							</span>
							<input bind:value={inferenceStart} type="date" />
						</label>
						<label>
							<span class="label-row">
								Pre-war months
								<button
									type="button"
									class="info-chip"
									aria-label="How many months before the conflict start form the undamaged baseline. 12 months averages over a full seasonal cycle; shorter baselines can mistake snow or vegetation changes for damage."
									data-tip="How many months before the conflict start form the undamaged baseline. 12 months averages over a full seasonal cycle; shorter baselines can mistake snow or vegetation changes for damage."
								>
									i
								</button>
							</span>
							<input bind:value={preIntervalInput} type="text" inputmode="decimal" placeholder="12" />
						</label>
						<label>
							<span class="label-row">
								Post-war months
								<button
									type="button"
									class="info-chip"
									aria-label="How many months after the inference start are tested for change. The satellite passes roughly every 12 days, so 2 months gives about 5 images — the sample the method was validated with. Shorter windows work but are noisier."
									data-tip="How many months after the inference start are tested for change. The satellite passes roughly every 12 days, so 2 months gives about 5 images — the sample the method was validated with. Shorter windows work but are noisier."
								>
									i
								</button>
							</span>
							<input bind:value={postIntervalInput} type="text" inputmode="decimal" placeholder="2" />
						</label>
					<label>
						<span class="label-row">
							Threshold
							<button
								type="button"
								class="info-chip"
								aria-label="How strong the radar change must be before a pixel counts as damaged. Higher values mean fewer but more confident detections; lower values find more damage but also more false alarms. The published method uses about 3."
								data-tip="How strong the radar change must be before a pixel counts as damaged. Higher values mean fewer but more confident detections; lower values find more damage but also more false alarms. The published method uses about 3."
							>
								i
							</button>
						</span>
						<input bind:value={thresholdInput} type="text" inputmode="decimal" placeholder="3.3" />
					</label>
				</div>
				<p class="copy subtle">Decimal months are allowed. `0.5` is roughly two weeks, and both `3.3` and `3,3` work.</p>
				{#if runAdvisories.length > 0}
					<div class="advisories">
						<strong>Worth knowing (the run can still start):</strong>
						<ul>
							{#each runAdvisories as advisory}
								<li>{advisory}</li>
							{/each}
						</ul>
					</div>
				{/if}
				{#if runBlockers.length > 0}
					<div class="requirements">
						<strong>Before you can start:</strong>
						<ul>
							{#each runBlockers as blocker}
								<li>{blocker}</li>
							{/each}
						</ul>
					</div>
				{/if}
				<div class="actions">
					<button class="primary" disabled={runLoading} on:click={handleStartAnalysis}>
						{runLoading
							? coverageChecking
								? 'Checking coverage...'
								: 'Queueing...'
							: savedAoiGeometry
								? 'Start analysis'
								: 'Save AOI first'}
					</button>
					<button
						class="secondary"
						disabled={coverageChecking || runLoading || !savedAoiGeometry}
						on:click={() => void checkCoverage()}
					>
						{coverageChecking ? 'Checking...' : 'Check imagery coverage'}
					</button>
				</div>
				{#if coverageCheck}
					{#if !coverageCheck.ok}
						<p class="error">{coverageCheck.message}</p>
					{:else if coverageCheck.coverage}
						<div class="coverage-panel">
							<strong>Radar imagery found</strong>
							<p class="copy">
								{coverageCheck.coverage.pre_scenes} baseline image{coverageCheck.coverage.pre_scenes === 1 ? '' : 's'}
								({coverageCheck.coverage.pre_window[0]} → {coverageCheck.coverage.pre_window[1]}) and
								{coverageCheck.coverage.post_scenes} post-war image{coverageCheck.coverage.post_scenes === 1 ? '' : 's'}
								({coverageCheck.coverage.post_window[0]} → {coverageCheck.coverage.post_window[1]}) across
								{coverageCheck.coverage.orbit_count} satellite orbit{coverageCheck.coverage.orbit_count === 1 ? '' : 's'}.
							</p>
							{#each coverageWarnings as warning}
								<p class="coverage-warning">⚠ {warning}</p>
							{/each}
						</div>
					{/if}
				{/if}
				{#if !canStartRun && primaryRunBlocker}
					<p class="error action-hint">{primaryRunBlocker}</p>
				{/if}
				{#if runError}
					<p class="error">{runError}</p>
				{/if}
			</section>

			<section class="card results">
				<header>
					<span class="step-tag">Step 4</span>
					<h3>Review the outputs and export</h3>
				</header>
				{#if !currentRun}
					<p class="copy">Start a run to populate the maps and export options.</p>
				{:else if currentRun.status === 'queued' || currentRun.status === 'running'}
					<div class="busy">
						<strong>{currentRun.status === 'queued' ? 'Queued for processing' : 'PWTT is running now'}</strong>
						{#if currentRun.status === 'running' && currentRun.progress_stage}
							<span>{currentRun.progress_stage}</span>
						{/if}
						<span>
							{elapsedMinutes(currentRun.created_at, pollNow) < 1
								? 'Started moments ago.'
								: `Running for ${elapsedMinutes(currentRun.created_at, pollNow)} min.`}
							Large areas can take 30+ minutes. The maps will appear here when the run finishes.
						</span>
					</div>
				{:else if currentRun.status === 'failed'}
					<p class="error">{currentRun.error_message ?? 'The analysis failed.'}</p>
					<div class="actions">
						<button class="secondary" disabled={retryingRunId === currentRun.id} on:click={() => retryRun(currentRun!.id)}>
							{retryingRunId === currentRun.id ? 'Retrying...' : 'Retry'}
						</button>
					</div>
					{#if retryError}
						<p class="error">{retryError}</p>
					{/if}
				{:else}
					<div class="metric-grid">
						<div title="Total area of built-up pixels whose change statistic exceeds the threshold.">
							<span>Damaged area</span><strong>{currentRun.summary?.damaged_area_ha} ha</strong>
						</div>
						<div
							title={currentRun.summary?.built_area_ha != null
								? `Damaged share of the ~${currentRun.summary.built_area_ha} ha of built-up land in this AOI. Farmland and water are excluded from the comparison.`
								: 'Damaged share of the whole AOI (older run — includes farmland and water, so this understates urban damage).'}
						>
							<span>{currentRun.summary?.built_area_ha != null ? 'Share of built-up area' : 'Share of AOI'}</span>
							<strong>{currentRun.summary?.damage_share_pct}%</strong>
						</div>
						<div title="Average change statistic across all built-up pixels. A confidence measure, not damage severity.">
							<span>Mean T-score</span><strong>{currentRun.summary?.mean_t_score}</strong>
						</div>
						<div title="Strongest change statistic anywhere in the AOI. A confidence measure, not damage severity.">
							<span>Peak T-score</span><strong>{currentRun.summary?.max_t_score}</strong>
						</div>
					</div>
					{#if currentRun.summary?.coverage}
						<p class="copy subtle">
							Based on {currentRun.summary.coverage.pre_scenes} baseline and {currentRun.summary.coverage.post_scenes}
							post-war radar image{currentRun.summary.coverage.post_scenes === 1 ? '' : 's'} across
							{currentRun.summary.coverage.orbit_count} orbit{currentRun.summary.coverage.orbit_count === 1 ? '' : 's'}.
							T-scores measure detection confidence — how clearly the radar signal changed — not how badly a structure is damaged.
						</p>
					{:else}
						<p class="copy subtle">
							T-scores measure detection confidence — how clearly the radar signal changed — not how badly a structure is damaged.
						</p>
					{/if}

					{#if currentRun.summary?.buildings}
						<div class="metric-grid building-grid">
							<div><span>Buildings checked</span><strong>{currentRun.summary.buildings.total_buildings}</strong></div>
							<div><span>Likely damaged</span><strong>{currentRun.summary.buildings.damaged_buildings}</strong></div>
							<div><span>Building share</span><strong>{currentRun.summary.buildings.damaged_share_pct}%</strong></div>
							<div>
								<span>Footprints</span>
								<strong>{currentRun.summary.buildings.available ? 'Microsoft Buildings' : 'Unavailable'}</strong>
							</div>
						</div>
						{#if currentRun.summary.buildings.reason}
							<p class="copy subtle">{currentRun.summary.buildings.reason}</p>
						{/if}
						{#if currentRun.summary.buildings.available}
							<p class="copy subtle">
								{#if currentRun.summary.buildings.min_building_area_m2}
									Buildings smaller than {currentRun.summary.buildings.min_building_area_m2} m² (most single houses)
									are not screened — they are below what the 10 m radar pixels can assess reliably.
								{/if}
								Severity tags (Elevated / High / Severe) rank detection confidence, not structural damage.
							</p>
						{/if}
						{#if currentRun.summary.buildings.top_damaged_buildings?.length}
							<div class="building-links">
								<strong>Likely damaged buildings</strong>
								<div class="building-chip-row">
									{#each currentRun.summary.buildings.top_damaged_buildings as building}
										<a class="building-chip" href={building.google_maps_url} target="_blank" rel="noreferrer">
											<span class={`building-tag ${building.category.toLowerCase()}`}>{building.category}</span>
											<span>{building.label}</span>
											<small>T {building.damage_probability}</small>
										</a>
									{/each}
								</div>
							</div>
						{/if}
					{/if}

					{#if currentRun.layers}
						{#key `${currentRun.id}-${currentRun.updated_at}`}
							<div class="triptych">
								<TilePanel
									title="Pre Destruction"
									imageUrl={currentRun.layers.pre_event_preview ?? ''}
									on:open={() =>
										openImageViewer({
										title: 'Pre Destruction',
										imageUrl: currentRun?.layers?.pre_event_preview ?? '',
										showLegend: false
									})}
								/>
								<TilePanel
									title="Post Destruction"
									imageUrl={currentRun.layers.post_event_preview ?? ''}
									on:open={() =>
										openImageViewer({
										title: 'Post Destruction',
										imageUrl: currentRun?.layers?.post_event_preview ?? '',
										showLegend: false
									})}
								/>
								<TilePanel
									title="PWTT"
									imageUrl={currentRun.layers.pwtt_preview ?? ''}
									showLegend={true}
									legendTitle="Detection confidence"
									legendItems={pwttLegend}
									on:open={() =>
										openImageViewer({
											title: 'PWTT',
											imageUrl: currentRun?.layers?.pwtt_preview ?? '',
											showLegend: true
										})}
								/>
							</div>
						{/key}
					{/if}

					<div class="actions">
						<a class="primary link" href={api.kmlUrl(currentRun.id)}>Export KML</a>
						<a class="secondary link" href={api.pngUrl(currentRun.id)}>Export PNG</a>
						<button class="secondary" type="button" on:click={() => reuseRunSettings(currentRun!)}>
							Reuse these settings
						</button>
					</div>
					<p class="copy subtle">
						"Reuse these settings" loads this run's AOI and parameters back into steps 2–3 so you can tweak the
						threshold or windows and compare a fresh run against this one.
					</p>
				{/if}
			</section>
		</div>

		<section class="history">
			<header>
				<h3>Recent runs</h3>
			</header>
			<div class="history-list">
				{#if recentRuns.length === 0}
					<p class="copy">No runs yet.</p>
				{:else}
					{#each recentRuns as run}
						<div class="history-row">
							<button class="history-item" on:click={() => openRun(run.id)}>
								<div>
									<strong>{run.aoi_name || `Run ${run.id}`}</strong>
									<span>#{run.id} · {formatRunDate(run.created_at)}</span>
								</div>
								<small>{run.status}</small>
							</button>
							<button
								class="ghost danger"
								type="button"
								disabled={deletingRunId === run.id || run.status === 'queued' || run.status === 'running'}
								on:click={() => removeRun(run.id)}
							>
								{deletingRunId === run.id ? 'Removing...' : 'Remove'}
							</button>
						</div>
					{/each}
				{/if}
				{#if historyError}
					<p class="error">{historyError}</p>
				{/if}
			</div>
		</section>
	</main>
</div>

<ImageModal open={imageViewer !== null} title={imageViewer?.title ?? ''} onClose={closeImageViewer}>
	{#if imageViewer && currentRun}
		<TilePanel
			title={imageViewer.title}
			imageUrl={imageViewer.imageUrl}
			showLegend={imageViewer.showLegend}
			legendItems={pwttLegend}
			expanded={true}
			on:open={() => {}}
		/>
	{/if}
</ImageModal>

<style>
	.page {
		display: grid;
		grid-template-columns: minmax(13.5rem, 15.5rem) minmax(0, 1fr);
		gap: 1rem;
		padding: 1rem;
		max-width: 1500px;
		margin: 0 auto;
		align-items: start;
	}

	.workspace {
		display: grid;
		gap: 0.9rem;
	}

	.topbar,
	.card,
	.history {
		border: 1px solid var(--line);
		border-radius: 24px;
		background: var(--panel);
		backdrop-filter: blur(18px);
		box-shadow: var(--shadow);
	}

	.topbar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: start;
		gap: 0.8rem;
		padding: 1rem 1.15rem;
	}

	.eyebrow,
	.step-tag {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: 0.78rem;
		font-weight: 700;
		color: var(--accent);
	}

	h2 {
		margin-top: 0.25rem;
		font-size: clamp(1.15rem, 1.6vw, 1.7rem);
		max-width: 24ch;
	}

	.status-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(5.25rem, 1fr));
		gap: 0.55rem;
	}

	.status-grid div,
	.metric-grid div {
		padding: 0.75rem 0.8rem;
		border-radius: 18px;
		background: rgba(255, 253, 248, 0.82);
		border: 1px solid rgba(29, 41, 53, 0.08);
	}

	.status-grid span,
	.metric-grid span,
	.history-item span {
		display: block;
		color: var(--muted);
		font-size: 0.85rem;
	}

	.status-grid strong,
	.metric-grid strong {
		display: block;
		margin-top: 0.2rem;
		font-size: 0.96rem;
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.9rem;
	}

	.card,
	.history {
		padding: 1.1rem;
	}

	header {
		display: grid;
		gap: 0.25rem;
		margin-bottom: 0.75rem;
	}

	.copy {
		margin: 0 0 0.85rem;
		line-height: 1.45;
		font-size: 0.92rem;
		color: var(--muted);
	}

	.field-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.75rem;
	}

	.field-grid.compact {
		grid-template-columns: minmax(0, 1fr);
		margin-bottom: 1rem;
	}

	.field-grid label,
	.credential-card,
	.actions,
	.busy {
		display: grid;
		gap: 0.45rem;
	}

	label span {
		font-size: 0.88rem;
		font-weight: 600;
		color: var(--muted);
	}

	.label-row {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}

	.info-chip {
		position: relative;
		display: inline-grid;
		place-items: center;
		width: 1.1rem;
		height: 1.1rem;
		padding: 0;
		border-radius: 50%;
		border: 1px solid rgba(29, 41, 53, 0.18);
		background: rgba(45, 127, 123, 0.08);
		color: var(--teal);
		font-size: 0.72rem;
		font-weight: 700;
		line-height: 1;
	}

	.info-chip::after {
		content: attr(data-tip);
		position: absolute;
		left: calc(100% + 0.55rem);
		top: 50%;
		transform: translateY(-50%);
		width: 15rem;
		padding: 0.65rem 0.75rem;
		border-radius: 12px;
		background: rgba(29, 41, 53, 0.96);
		color: white;
		font-size: 0.78rem;
		font-weight: 500;
		line-height: 1.4;
		text-align: left;
		opacity: 0;
		pointer-events: none;
		box-shadow: 0 18px 36px rgba(29, 41, 53, 0.22);
		z-index: 10;
	}

	.info-chip::before {
		content: '';
		position: absolute;
		left: calc(100% + 0.2rem);
		top: 50%;
		transform: translateY(-50%);
		border-top: 6px solid transparent;
		border-bottom: 6px solid transparent;
		border-right: 6px solid rgba(29, 41, 53, 0.96);
		opacity: 0;
		pointer-events: none;
		z-index: 10;
	}

	.info-chip:hover::after,
	.info-chip:hover::before,
	.info-chip:focus-visible::after,
	.info-chip:focus-visible::before {
		opacity: 1;
	}

	input,
	select {
		padding: 0.78rem 0.9rem;
		border-radius: 14px;
		border: 1px solid rgba(29, 41, 53, 0.12);
		background: var(--panel-strong);
		color: var(--ink);
	}

	.credential-card {
		padding: 0.78rem 0.9rem;
		border-radius: 14px;
		border: 1px solid rgba(29, 41, 53, 0.12);
		background: var(--panel-strong);
		align-content: start;
	}

	.credential-card strong {
		word-break: break-all;
		font-size: 0.92rem;
	}

	.credential-card small,
	.subtle {
		color: var(--muted);
	}

	.actions {
		margin-top: 0.85rem;
		grid-auto-flow: column;
		justify-content: start;
		align-items: center;
		gap: 0.55rem;
		flex-wrap: wrap;
	}

	.action-hint {
		margin-top: 0.55rem;
	}

	button,
	.link {
		padding: 0.7rem 1rem;
		border-radius: 999px;
		border: none;
		text-decoration: none;
		font-size: 0.9rem;
	}

	.primary {
		background: linear-gradient(135deg, var(--accent), #df8a47);
		color: white;
		font-weight: 700;
	}

	.secondary {
		background: rgba(45, 127, 123, 0.12);
		color: var(--teal);
		font-weight: 700;
	}

	.primary:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.success {
		margin-top: 0.9rem;
		color: var(--olive);
	}

	.error {
		margin-top: 0.9rem;
		color: #a13624;
		font-weight: 600;
	}

	.aoi-size-hint {
		margin-top: 0.6rem;
		font-size: 0.85rem;
		color: var(--muted);
	}

	.aoi-size-warn {
		color: #b45309;
		font-weight: 600;
	}

	.aoi-size-block {
		color: #a13624;
		font-weight: 700;
	}

	.results {
		grid-column: 1 / -1;
	}

	.busy {
		padding: 0.9rem 1rem;
		border-radius: 18px;
		background: rgba(83, 98, 79, 0.08);
		color: var(--olive);
	}

	.requirements,
	.advisories {
		margin-top: 0.2rem;
		padding: 0.9rem 1rem;
		border-radius: 16px;
		background: rgba(244, 201, 153, 0.2);
		border: 1px solid rgba(196, 79, 29, 0.14);
	}

	.advisories {
		background: rgba(246, 215, 67, 0.14);
		border-color: rgba(142, 108, 0, 0.18);
		margin-bottom: 0.75rem;
	}

	.requirements strong,
	.advisories strong {
		display: block;
		margin-bottom: 0.45rem;
	}

	.requirements ul,
	.advisories ul {
		margin: 0;
		padding-left: 1rem;
		color: var(--muted);
	}

	.requirements li + li,
	.advisories li + li {
		margin-top: 0.3rem;
	}

	.coverage-panel {
		margin-top: 0.85rem;
		padding: 0.9rem 1rem;
		border-radius: 16px;
		background: rgba(45, 127, 123, 0.08);
		border: 1px solid rgba(45, 127, 123, 0.16);
	}

	.coverage-panel strong {
		display: block;
		margin-bottom: 0.35rem;
		color: var(--teal);
	}

	.coverage-panel .copy {
		margin-bottom: 0;
	}

	.coverage-warning {
		margin: 0.5rem 0 0;
		font-size: 0.88rem;
		font-weight: 600;
		color: #b45309;
	}

	.metric-grid,
	.triptych {
		display: grid;
		gap: 1rem;
	}

	.metric-grid {
		grid-template-columns: repeat(4, minmax(0, 1fr));
		margin-bottom: 1rem;
	}

	.building-grid {
		margin-top: -0.15rem;
	}

	.triptych {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}

	.building-links {
		display: grid;
		gap: 0.8rem;
		margin: 0 0 1rem;
		padding: 1rem 1.05rem;
		border-radius: 18px;
		background: rgba(255, 250, 240, 0.85);
		border: 1px solid rgba(29, 41, 53, 0.08);
	}

	.building-links strong {
		font-size: 0.95rem;
	}

	.building-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.65rem;
	}

	.building-chip {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.55rem 0.75rem;
		border-radius: 999px;
		border: 1px solid rgba(29, 41, 53, 0.08);
		background: rgba(255, 255, 255, 0.9);
		color: var(--ink);
		text-decoration: none;
	}

	.building-chip small {
		color: var(--muted);
	}

	.building-tag {
		display: inline-flex;
		align-items: center;
		padding: 0.2rem 0.48rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.building-tag.elevated {
		background: rgba(246, 215, 67, 0.25);
		color: #8e6c00;
	}

	.building-tag.high {
		background: rgba(232, 93, 4, 0.18);
		color: #ad4300;
	}

	.building-tag.severe {
		background: rgba(95, 15, 64, 0.16);
		color: #5f0f40;
	}

	.history-list {
		display: grid;
		gap: 0.75rem;
	}

	.history-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 0.6rem;
		align-items: center;
	}

	.history-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.8rem 0.9rem;
		border-radius: 14px;
		border: 1px solid rgba(29, 41, 53, 0.08);
		background: rgba(255, 253, 248, 0.85);
	}

	.ghost {
		padding: 0.65rem 0.9rem;
		border-radius: 999px;
		border: 1px solid rgba(29, 41, 53, 0.1);
		background: rgba(255, 253, 248, 0.85);
		color: var(--ink);
	}

	.danger {
		color: #a13624;
	}

	.history-item strong {
		display: block;
	}

	.history-item small {
		text-transform: uppercase;
		font-weight: 700;
		letter-spacing: 0.06em;
		color: var(--accent);
	}

	@media (max-width: 1380px) {
		.cards,
		.metric-grid,
		.triptych {
			grid-template-columns: 1fr;
		}

		.results {
			grid-column: auto;
		}
	}

	@media (max-width: 1180px) {
		.page {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 780px) {
		.field-grid,
		.status-grid,
		.actions {
			grid-template-columns: 1fr;
			grid-auto-flow: row;
		}

		.info-chip::after {
			left: auto;
			right: 0;
			top: calc(100% + 0.55rem);
			transform: none;
		}

		.info-chip::before {
			left: auto;
			right: 0.2rem;
			top: calc(100% + 0.15rem);
			transform: rotate(90deg);
		}

		.history-row {
			grid-template-columns: 1fr;
		}
	}
</style>
