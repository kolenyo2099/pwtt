<script lang="ts">
	export let steps: { id: string; label: string; blurb: string }[] = [];
	export let current = 0;
</script>

<aside class="rail">
	<h1>PWTT Wizard</h1>

	<div class="steps">
		{#each steps as step, index}
			<div class:active={index === current} class:complete={index < current} class="step">
				<div class="number">{index + 1}</div>
				<div>
					<strong>{step.label}</strong>
					<span>{step.blurb}</span>
				</div>
			</div>
		{/each}
	</div>
</aside>

<style>
	.rail {
		display: grid;
		gap: 1rem;
		padding: 1.2rem;
		border-radius: 12px;
		background:
			linear-gradient(180deg, var(--navy) 0%, var(--navy-deep) 100%),
			linear-gradient(120deg, rgba(253, 181, 21, 0.16), transparent 45%);
		color: white;
		box-shadow: var(--shadow);
		position: sticky;
		top: 1rem;
		border-top: 3px solid var(--gold);
	}

	h1 {
		font-family: 'Source Serif 4', serif;
		font-size: 1.35rem;
		line-height: 1.1;
	}

	.steps {
		display: grid;
		gap: 0.7rem;
	}

	.step {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.7rem;
		align-items: start;
		padding: 0.85rem 0.9rem;
		border-radius: 10px;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.08);
	}

	.step strong,
	.step span {
		display: block;
	}

	.step span {
		margin-top: 0.2rem;
		color: rgba(255, 255, 255, 0.67);
		font-size: 0.83rem;
		line-height: 1.35;
	}

	.number {
		display: grid;
		place-items: center;
		width: 1.8rem;
		height: 1.8rem;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.1);
		font-family: 'IBM Plex Mono', monospace;
		font-weight: 600;
		font-size: 0.85rem;
	}

	.active {
		background: rgba(253, 181, 21, 0.18);
		border-color: rgba(253, 181, 21, 0.55);
	}

	.active .number {
		background: var(--gold);
		color: var(--navy);
	}

	.complete .number {
		background: rgba(0, 85, 58, 0.4);
	}

	@media (max-width: 1180px) {
		.rail {
			position: static;
		}
	}
</style>
