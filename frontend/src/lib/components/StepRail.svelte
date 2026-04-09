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
		border-radius: 24px;
		background:
			linear-gradient(180deg, rgba(29, 41, 53, 0.92), rgba(38, 49, 64, 0.94)),
			linear-gradient(120deg, rgba(244, 201, 153, 0.2), transparent 45%);
		color: white;
		box-shadow: var(--shadow);
		position: sticky;
		top: 1rem;
	}

	h1 {
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
		border-radius: 16px;
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
		font-family: 'Space Grotesk', sans-serif;
		font-size: 0.85rem;
	}

	.active {
		background: rgba(196, 79, 29, 0.22);
		border-color: rgba(244, 201, 153, 0.5);
	}

	.complete .number {
		background: rgba(88, 170, 124, 0.35);
	}

	@media (max-width: 1180px) {
		.rail {
			position: static;
		}
	}
</style>
