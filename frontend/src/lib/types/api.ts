export type AuthSettings = {
	configured: boolean;
	project_id: string | null;
	auth_mode: 'ambient' | 'missing';
	credentials_present: boolean;
	credentials_path: string | null;
};

export type BrowserAuthStatus = {
	status: 'idle' | 'running' | 'completed' | 'failed';
	message: string;
	credentials_present: boolean;
	credentials_path: string | null;
};

export type RunInput = {
	aoi_name?: string | null;
	aoi_geojson: GeoJSON.Geometry;
	war_start: string;
	inference_start: string;
	pre_interval: number;
	post_interval: number;
	threshold: number;
};

export type RunSummary = {
	id: number;
	status: 'queued' | 'running' | 'completed' | 'failed';
	aoi_name: string | null;
	created_at: string;
	updated_at: string;
	error_message?: string | null;
	progress_stage?: string | null;
};

export type CoverageSummary = {
	pre_scenes: number;
	post_scenes: number;
	orbit_count: number;
	min_pre_scenes_per_orbit: number;
	min_post_scenes_per_orbit: number;
	pre_window: [string, string];
	post_window: [string, string];
};

export type PreflightResult = {
	ok: boolean;
	message?: string | null;
	coverage?: CoverageSummary | null;
};

export type RunDetail = RunSummary & {
	aoi_geojson: GeoJSON.Geometry;
	parameters: RunInput;
	summary?: {
		damaged_area_ha: number;
		built_area_ha?: number | null;
		damage_share_pct: number;
		aoi_share_pct?: number | null;
		mean_t_score: number;
		max_t_score: number;
		damaged_pixel_estimate: number;
		coverage?: CoverageSummary | null;
		buildings?: {
			available: boolean;
			reason?: string | null;
			total_buildings: number;
			damaged_buildings: number;
			damaged_share_pct: number;
			asset_ids?: string[] | null;
			min_building_area_m2?: number | null;
			top_damaged_buildings?: Array<{
				label: string;
				category: string;
				damage_probability: number;
				google_maps_url: string;
			}> | null;
		} | null;
	} | null;
	layers?: {
		pre_event: string;
		post_event: string;
		pwtt_overlay: string;
		buildings_overlay?: string | null;
		pre_event_preview?: string | null;
		post_event_preview?: string | null;
		pwtt_preview?: string | null;
	} | null;
};
