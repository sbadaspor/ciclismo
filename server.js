const express = require('express');
const cors = require('cors');
const axios = require('axios');
const cheerio = require('cheerio');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Serve os ficheiros estáticos (o teu HTML)
app.use(express.static(path.join(__dirname, 'public')));

// ──────────────────────────────────────────────
//  HEADERS comuns para simular browser
// ──────────────────────────────────────────────
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'pt-PT,pt;q=0.9,en;q=0.8',
  'Cache-Control': 'no-cache',
};

// ──────────────────────────────────────────────
//  ROTA: Buscar startlist de uma corrida
//  GET /api/startlist?race=tour-de-france/2025
// ──────────────────────────────────────────────
app.get('/api/startlist', async (req, res) => {
  const { race } = req.query;
  if (!race) return res.status(400).json({ error: 'Parâmetro "race" obrigatório.' });

  try {
    const url = `https://www.procyclingstats.com/race/${race}/startlist`;
    const { data } = await axios.get(url, { headers: HEADERS, timeout: 10000 });
    const $ = cheerio.load(data);

    const cyclists = [];

    // PCS usa tabela com class "basic" ou rows com links de riders
    $('ul.startlist li, table.basic tbody tr').each((i, el) => {
      const nameEl = $(el).find('a[href*="/rider/"]').first();
      const name = nameEl.text().trim();
      if (!name) return;

      const teamEl = $(el).find('a[href*="/team/"]').first();
      const team = teamEl.text().trim();

      const bib = $(el).find('.bib, td:first-child').first().text().trim();

      cyclists.push({ id: `c_${i}`, name, team, bib });
    });

    if (cyclists.length === 0) {
      return res.status(404).json({ error: 'Nenhum ciclista encontrado. Verifica o Race ID.' });
    }

    res.json({ race, count: cyclists.length, cyclists });
  } catch (err) {
    console.error('Startlist error:', err.message);
    res.status(500).json({ error: 'Erro ao buscar startlist: ' + err.message });
  }
});

// ──────────────────────────────────────────────
//  ROTA: Buscar resultado geral (GC) atual
//  GET /api/results?race=tour-de-france/2025
// ──────────────────────────────────────────────
app.get('/api/results', async (req, res) => {
  const { race } = req.query;
  if (!race) return res.status(400).json({ error: 'Parâmetro "race" obrigatório.' });

  try {
    const url = `https://www.procyclingstats.com/race/${race}/gc`;
    const { data } = await axios.get(url, { headers: HEADERS, timeout: 10000 });
    const $ = cheerio.load(data);

    const top20 = [];

    // Tabela de resultados GC do PCS
    $('table.basic tbody tr').each((i, el) => {
      if (i >= 20) return false; // só top 20

      const tds = $(el).find('td');
      const pos = $(tds[0]).text().trim();
      const nameEl = $(el).find('a[href*="/rider/"]').first();
      const name = nameEl.text().trim();
      if (!name) return;

      const teamEl = $(el).find('a[href*="/team/"]').first();
      const team = teamEl.text().trim();

      const timeEl = $(tds).last();
      const time = timeEl.text().trim();

      top20.push({ pos: parseInt(pos) || i + 1, name, team, time });
    });

    // Camisolas — PCS tem secção de jersey leaders
    const jerseys = {};
    $('div.jersey-leader, .classification-leaders li, .jersey').each((i, el) => {
      const type = $(el).attr('class') || '';
      const name = $(el).find('a[href*="/rider/"]').first().text().trim();
      if (!name) return;
      if (type.includes('points') || type.includes('green')) jerseys.points = name;
      if (type.includes('mountain') || type.includes('polka')) jerseys.mountain = name;
      if (type.includes('youth') || type.includes('white')) jerseys.youth = name;
    });

    if (top20.length === 0) {
      return res.status(404).json({ error: 'Sem resultados disponíveis. A corrida ainda não começou ou o Race ID está errado.' });
    }

    res.json({ race, top20, jerseys });
  } catch (err) {
    console.error('Results error:', err.message);
    res.status(500).json({ error: 'Erro ao buscar resultados: ' + err.message });
  }
});

// ──────────────────────────────────────────────
//  ROTA: Health check
// ──────────────────────────────────────────────
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', version: '1.0.0', timestamp: new Date().toISOString() });
});

// ──────────────────────────────────────────────
//  Fallback → serve o HTML principal
// ──────────────────────────────────────────────
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`✅ VeloAposta server a correr em http://localhost:${PORT}`);
});
