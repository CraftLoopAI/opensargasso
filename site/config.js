// Set this to your GitHub "owner/repo" so the report button opens the right form.
// `tiles` is the basemap. OpenStreetMap's public tile server allows a community site like
// this one (https://operations.osmfoundation.org/policies/tiles/); if traffic outgrows it,
// change the URL and attribution here. The dark theme's tile filter and sea color in
// style.css are tuned to OpenStreetMap's colors.
window.OPENSARGASSO = {
  repo: "CraftLoopAI/opensargasso",
  tiles: {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18
  }
};
