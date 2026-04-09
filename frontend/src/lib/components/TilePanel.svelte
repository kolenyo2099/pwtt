<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	export let title = '';
	export let imageUrl = '';
	export let expanded = false;
	export let showLegend = false;
	export let legendItems: Array<{ color: string; label: string }> = [];

	const dispatch = createEventDispatcher<{ open: void }>();

	let loaded = false;
	let loadError = false;

	$: if (imageUrl) {
		loaded = false;
		loadError = false;
	}
</script>

<div class:expanded class="panel">
	<div class="frame">
		<div class="panel-head">
			<div class="caption">{title}</div>
			<button class="panel-open" type="button" on:click={() => dispatch('open')} aria-label={`Open ${title} larger`}>
				Open larger
			</button>
		</div>

		<div class="image-shell">
			{#if !imageUrl || loadError}
				<div class="image placeholder">Preview unavailable</div>
			{:else if !loaded}
				<div class="image placeholder loading">Loading…</div>
			{/if}
			{#if imageUrl}
				<img
					class="image"
					class:expanded-image={expanded}
					src={imageUrl}
					alt={title}
					style:display={loaded ? 'block' : 'none'}
					on:load={() => { loaded = true; }}
					on:error={() => { loadError = true; }}
				/>
			{/if}
		</div>

		{#if showLegend}
			<div class="legend">
				<strong>Legend</strong>
				<div class="legend-row">
					{#each legendItems as item}
						<div class="legend-item">
							<span class="swatch" style={`--swatch:${item.color}`}></span>
							<span>{item.label}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</div>

<style>
	.panel {
		margin: 0;
		position: relative;
	}

	.frame {
		display: grid;
		gap: 0.85rem;
		padding: 0.8rem;
		border-radius: 28px;
		background:
			linear-gradient(180deg, rgba(255, 253, 248, 0.98), rgba(241, 237, 228, 0.94)),
			radial-gradient(circle at top, rgba(244, 201, 153, 0.18), transparent 55%);
		border: 1px solid rgba(29, 41, 53, 0.08);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.82),
			0 18px 34px rgba(29, 41, 53, 0.08);
	}

	.panel-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.8rem;
	}

	.image-shell {
		aspect-ratio: 1.18 / 1;
		border-radius: 22px;
		overflow: hidden;
		border: 1px solid rgba(29, 41, 53, 0.12);
		background:
			linear-gradient(180deg, rgba(212, 210, 204, 0.82), rgba(233, 230, 223, 0.74)),
			radial-gradient(circle at top, rgba(255, 255, 255, 0.32), transparent 58%);
		box-shadow:
			inset 0 0 0 1px rgba(255, 255, 255, 0.35),
			0 6px 16px rgba(29, 41, 53, 0.08);
	}

	.image {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.placeholder {
		display: grid;
		place-items: center;
		color: var(--muted);
		font-size: 0.95rem;
	}

	.loading {
		animation: pulse 1.4s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	.panel.expanded .image-shell {
		aspect-ratio: auto;
		min-height: min(78vh, 48rem);
	}

	.expanded-image {
		object-fit: contain;
		background: #eeeadf;
	}

	.panel-open {
		padding: 0.45rem 0.7rem;
		border-radius: 999px;
		border: 1px solid rgba(29, 41, 53, 0.14);
		background: rgba(255, 253, 248, 0.9);
		color: var(--ink);
		font-size: 0.8rem;
	}

	.caption {
		font-family: 'Space Grotesk', sans-serif;
		font-size: 1.25rem;
		font-weight: 700;
	}

	.legend {
		display: grid;
		gap: 0.45rem;
		padding: 0.25rem 0.1rem 0;
	}

	.legend strong {
		font-size: 0.85rem;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.legend-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.7rem 1rem;
	}

	.legend-item {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		font-size: 0.85rem;
		color: var(--ink);
	}

	.swatch {
		width: 0.8rem;
		height: 0.8rem;
		border-radius: 999px;
		background: var(--swatch);
		box-shadow: inset 0 0 0 1px rgba(29, 41, 53, 0.12);
	}
</style>
