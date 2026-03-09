<script>
  import { api } from '$shared/lib/api.js';
  import ContactList from '$shared/components/contacts/ContactList.svelte';
  import { push } from 'svelte-spa-router';

  let contacts = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  async function loadContacts() {
    loading = true;
    error = null;
    try {
      const data = await api.get(`/api/contacts/?page=${page}`);
      contacts = data.results;
      count = data.count;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function handleSelect(contact) {
    push(`/contacts/${contact.contact_id}`);
  }

  $effect(() => {
    loadContacts();
  });
</script>

<h2>Contacts ({count})</h2>

<p><a href="#/contacts/new">New Contact</a></p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else}
  <ContactList {contacts} onSelect={handleSelect} />

  {#if count > 25}
    <p>
      {#if page > 1}
        <button onclick={() => { page--; }}>Previous</button>
      {/if}
      Page {page}
      {#if page * 25 < count}
        <button onclick={() => { page++; }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
