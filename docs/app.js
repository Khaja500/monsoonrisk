/* Bootstrap: load both data files, render both parts, wire the chrome. */
import { renderWeather, heroWeatherTiles } from './weather.js';
import { renderGame, heroGameTiles } from './game.js';
import { fmt } from './chart.js';

const el = (id) => document.getElementById(id);
const h = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

/* theme toggle, remembered per viewer where storage is available */
(function theme() {
  let saved = null;
  try { saved = localStorage.getItem('monsoonrisk-theme'); } catch { /* storage blocked */ }
  if (saved === 'dark' || saved === 'light') document.documentElement.setAttribute('data-theme', saved);
  el('theme-toggle').addEventListener('click', () => {
    const now = document.documentElement.getAttribute('data-theme');
    const dark = now === 'dark' || (!now && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = dark ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('monsoonrisk-theme', next); } catch { /* ignore */ }
    if (window.__rerender) window.__rerender();
  });
})();

/* section highlighting in the nav */
(function nav() {
  const links = [...document.querySelectorAll('#nav a')];
  const obs = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      links.forEach((a) => a.classList.toggle('active', a.getAttribute('href') === `#${e.target.id}`));
    }
  }, { rootMargin: '-45% 0px -50% 0px' });
  for (const id of ['weather', 'israeli', 'method']) obs.observe(el(id));
})();

function registerTable(meta) {
  el('register-table').innerHTML = `
    <thead><tr><th>Source</th><th>Used for</th><th>Status</th></tr></thead>
    <tbody>${meta.data_register.map((r) => `<tr><td>${h(r.source)}</td><td>${h(r.use)}</td>
      <td>${h(r.status)}</td></tr>`).join('')}</tbody>`;
}

function sourceList(weather, game) {
  const items = [];
  for (const [key, city] of Object.entries(weather.cities)) {
    for (const [name, block] of Object.entries(city.forecast || {})) {
      if (block && typeof block === 'object' && block.source) {
        items.push(`<li><strong>${h(city.label)} — ${h(name.replace(/_/g, ' '))}:</strong> ${h(block.source)}</li>`);
      }
    }
    if (city.station_normal_source) {
      items.push(`<li><strong>${h(city.label)} — settlement normal:</strong> ${h(city.station_normal_source)}</li>`);
    }
  }
  for (const s of Object.values(game.inputs.sources)) items.push(`<li><strong>NIFTY 50 inputs:</strong> ${h(s)}</li>`);
  el('source-list').innerHTML = `<ul>${items.join('')}</ul>`;
}

async function main() {
  const [weather, game] = await Promise.all([
    fetch('data/weather.json').then((r) => r.json()),
    fetch('data/game.json').then((r) => r.json()),
  ]);

  el('hero-tiles').innerHTML = heroWeatherTiles(weather) + heroGameTiles(game);
  renderWeather(weather);
  renderGame(game);
  registerTable(weather.meta);
  sourceList(weather, game);

  const b = weather.meta.baseline;
  el('footer-meta').textContent =
    `data as of ${weather.meta.asof} · IMD gridded rainfall ${b.history_start_year}–2025 plus a provisional 2026 · `
    + `normals ${b.lpa_start_year}–${b.lpa_end_year}, ${b.smoothing_window}-day smoothing · `
    + `NIFTY 50 inputs as of ${game.inputs.asof}`;

  window.__rerender = () => { renderWeather(weather); renderGame(game); };
}

main().catch((err) => {
  document.querySelector('main').insertAdjacentHTML('afterbegin',
    `<div class="callout warn"><strong>Could not load the data files.</strong> ${h(err.message)}</div>`);
  console.error(err);
});
