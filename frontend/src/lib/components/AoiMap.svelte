<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';

	export let value: GeoJSON.Geometry | null = null;

	const dispatch = createEventDispatcher<{ change: GeoJSON.Geometry | null }>();

	type SearchResult = {
		place_id: number;
		display_name: string;
		lat: string;
		lon: string;
		boundingbox?: string[];
	};

	let container: HTMLDivElement;
	let map: any;
	let featureGroup: any;
	let leafletReady = false;
	let searchText = '';
	let searchResults: SearchResult[] = [];
	let searching = false;
	let searchMessage = '';

	function emitGeometry(layer: any) {
		const geometry = layer.toGeoJSON().geometry as GeoJSON.Geometry;
		value = geometry;
		dispatch('change', geometry);
	}

	function syncLayer() {
		if (!leafletReady || !featureGroup) {
			return;
		}

		featureGroup.clearLayers();
		if (!value) {
			return;
		}

		const L = (window as any).L;
		const layer = L.geoJSON({ type: 'Feature', properties: {}, geometry: value });
		layer.eachLayer((entry: any) => featureGroup.addLayer(entry));

		const bounds = featureGroup.getBounds();
		if (bounds.isValid()) {
			map.fitBounds(bounds.pad(0.25));
		}
	}

	function zoomToSearchResult(result: SearchResult) {
		if (!leafletReady || !map) {
			return;
		}

		const L = (window as any).L;
		const bounds = result.boundingbox;
		if (bounds && bounds.length === 4) {
			const south = Number(bounds[0]);
			const north = Number(bounds[1]);
			const west = Number(bounds[2]);
			const east = Number(bounds[3]);
			map.fitBounds(
				L.latLngBounds(
					L.latLng(south, west),
					L.latLng(north, east)
				),
				{ padding: [20, 20] }
			);
		} else {
			map.setView([Number(result.lat), Number(result.lon)], 12);
		}

		searchText = result.display_name;
		searchResults = [];
		searchMessage = '';
	}

	async function searchPlaces() {
		const query = searchText.trim();
		searchMessage = '';
		searchResults = [];

		if (!query) {
			searchMessage = 'Enter a place name to search.';
			return;
		}

		searching = true;
		try {
			const url = new URL('https://nominatim.openstreetmap.org/search');
			url.searchParams.set('q', query);
			url.searchParams.set('format', 'jsonv2');
			url.searchParams.set('limit', '5');

			const response = await fetch(url.toString(), {
				headers: {
					Accept: 'application/json'
				}
			});

			if (!response.ok) {
				throw new Error('Search service unavailable.');
			}

			searchResults = (await response.json()) as SearchResult[];
			if (searchResults.length === 0) {
				searchMessage = 'No matching places found.';
			}
		} catch (error) {
			searchMessage = error instanceof Error ? error.message : 'Unable to search for places.';
		} finally {
			searching = false;
		}
	}

	function onSearchKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			event.preventDefault();
			searchPlaces();
		}
	}

	onMount(async () => {
		const leafletModule = await import('leaflet');
		const L = (leafletModule as any).default ?? leafletModule;
		(window as any).L = L;
		await import('leaflet-draw');

		delete (L.Icon.Default.prototype as any)._getIconUrl;
		L.Icon.Default.mergeOptions({
			iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
			iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
			shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png'
		});

		map = L.map(container, {
			zoomControl: true,
			attributionControl: true
		}).setView([33.15, 35.35], 8);

		L.tileLayer(
			'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
			{
				maxZoom: 19,
				attribution: 'Esri'
			}
		).addTo(map);

		featureGroup = new L.FeatureGroup();
		map.addLayer(featureGroup);

		const drawControl = new L.Control.Draw({
			position: 'topright',
			draw: {
				polygon: {
					showArea: false
				},
				rectangle: {
					showArea: false
				},
				polyline: false,
				circle: false,
				marker: false,
				circlemarker: false
			},
			edit: {
				featureGroup,
				remove: true
			}
		});
		map.addControl(drawControl);

		map.on('draw:created', (event: any) => {
			featureGroup.clearLayers();
			featureGroup.addLayer(event.layer);
			emitGeometry(event.layer);
		});

		map.on('draw:edited', () => {
			const firstLayer = featureGroup.getLayers()[0];
			if (firstLayer) {
				emitGeometry(firstLayer);
			}
		});

		map.on('draw:deleted', () => {
			value = null;
			dispatch('change', null);
		});

		leafletReady = true;
		syncLayer();
	});

	$: syncLayer();
</script>

<div class="map-shell">
	<div class="search-bar">
		<input
			bind:value={searchText}
			type="text"
			placeholder="Search for a city, district, or landmark"
			on:keydown={onSearchKeydown}
		/>
		<button class="search-button" type="button" on:click={searchPlaces} disabled={searching}>
			{searching ? 'Searching...' : 'Search'}
		</button>
	</div>

	{#if searchResults.length > 0}
		<div class="search-results">
			{#each searchResults as result}
				<button class="search-result" type="button" on:click={() => zoomToSearchResult(result)}>
					{result.display_name}
				</button>
			{/each}
		</div>
	{:else if searchMessage}
		<p class="search-message">{searchMessage}</p>
	{/if}

	<div bind:this={container} class="map"></div>
</div>

<style>
	.map-shell {
		display: grid;
		gap: 0.65rem;
	}

	.search-bar {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 0.55rem;
	}

	.search-bar input {
		padding: 0.78rem 0.9rem;
		border-radius: 8px;
		border: 1px solid rgba(20, 36, 58, 0.14);
		background: rgba(255, 255, 255, 0.92);
		color: var(--ink);
	}

	.search-button,
	.search-result {
		border: none;
		cursor: pointer;
	}

	.search-button {
		padding: 0.78rem 1rem;
		border-radius: 999px;
		background: rgba(0, 74, 174, 0.12);
		color: var(--blue-accent);
		font-weight: 700;
	}

	.search-results {
		display: grid;
		gap: 0.45rem;
	}

	.search-result {
		padding: 0.72rem 0.85rem;
		border-radius: 8px;
		text-align: left;
		background: rgba(255, 255, 255, 0.92);
		border: 1px solid rgba(20, 36, 58, 0.1);
		color: var(--ink);
	}

	.search-message {
		margin: 0;
		font-size: 0.88rem;
		color: var(--muted);
	}

	.map {
		width: 100%;
		height: 26rem;
		border-radius: 12px;
		overflow: hidden;
		border: 1px solid rgba(20, 36, 58, 0.14);
	}

	@media (max-width: 720px) {
		.search-bar {
			grid-template-columns: 1fr;
		}
	}
</style>
