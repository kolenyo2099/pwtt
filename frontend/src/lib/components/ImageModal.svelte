<script lang="ts">
	export let open = false;
	export let title = '';
	export let onClose: () => void = () => {};
</script>

{#if open}
	<div
		class="backdrop"
		role="button"
		tabindex="0"
		aria-label="Close enlarged image"
		on:mousedown={onClose}
		on:keydown={(event) => {
			if (event.key === 'Escape' || event.key === 'Enter' || event.key === ' ') {
				onClose();
			}
		}}
	>
		<div class="dialog" role="dialog" aria-modal="true" aria-label={title} tabindex="-1" on:mousedown|stopPropagation>
			<div class="dialog-head">
				<strong>{title}</strong>
				<button type="button" on:click={onClose}>Close</button>
			</div>
			<slot />
		</div>
	</div>
{/if}

<style>
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 1200;
		display: grid;
		place-items: center;
		padding: 1rem;
		background: rgba(1, 1, 51, 0.65);
		backdrop-filter: blur(8px);
	}

	.dialog {
		width: min(90rem, 100%);
		max-height: calc(100vh - 2rem);
		overflow: auto;
		padding: 1rem;
		border-radius: 12px;
		background: #f4f6f8;
		border-top: 3px solid var(--gold);
		box-shadow: 0 24px 80px rgba(1, 1, 51, 0.35);
	}

	.dialog-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		margin-bottom: 0.8rem;
	}

	.dialog-head strong {
		font-family: 'Source Serif 4', serif;
		font-size: 1.1rem;
	}

	button {
		padding: 0.55rem 0.8rem;
		border: 1px solid rgba(20, 36, 58, 0.16);
		border-radius: 999px;
		background: white;
		color: var(--blue-accent);
	}
</style>
