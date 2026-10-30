"""Fetch sightings from Elanco's API (timeouts, retries), clean them, and replace the local copy in one transaction.
Falls back to data/seed.json if the very first sync fails."""
