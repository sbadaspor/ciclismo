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
// HEADERS comuns para simular browser
// ──────────────────────────────────────────────
const HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-PT,pt;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Referer': 'https://www.procyclingstats.com/',
};

// ──────────────────────────────────────────────
// ROTA: Buscar startlist de uma corrida
// GET /api/startlist?race=paris-roubaix/2026
// ──────────────────────────────────────────────
app.get('/api/startlist', async (req, res) => {
    let { race } = req.query;
    if (!race) return res.status(400).json({ error: 'Parâmetro "race" obrigatório.' });

          // Normalizar: remover /startlist do final se vier com ele
          race = race.replace(/\/startlist\/?$/, '');

          try {
                const url = `https://www.procyclingstats.com/race/${race}/startlist`;
                console.log('Fetching startlist:', url);

      const { data } = await axios.get(url, { headers: HEADERS, timeout: 15000 });
                const $ = cheerio.load(data);
                const cyclists = [];

      // PCS usa ul.startlist_v4 > li (por equipa) > ul > li (por ciclista)
      $('ul.startlist_v4 > li').each((teamIdx, teamEl) => {
              const teamName = $(teamEl).find('a.team').first().text().trim();
              $(teamEl).find('ul > li').each((i, riderEl) => {
                        const nameEl = $(riderEl).find('a').first();
                        const name = nameEl.text().trim();
                        if (!name) return;
                        const bibEl = $(riderEl).find('span.bib');
                        const bib = bibEl.text().trim().replace(/-/g, '').trim();
                        cyclists.push({
                                    id: `c_${teamIdx}_${i}`,
                                    name,
                                    team: teamName,
                                    bib,
                        });
              });
      });

      // Fallback: tentar seletor antigo se a estrutura nova não retornar nada
      if (cyclists.length === 0) {
              $('ul.startlist li, table.basic tbody tr').each((i, el) => {
                        const nameEl = $(el).find('a[href*="/rider/"]').first();
                        const name = nameEl.text().trim();
                        if (!name) return;
                        const teamEl = $(el).find('a[href*="/team/"]').first();
                        const team = teamEl.text().trim();
                        const bib = $(el).find('.bib, td:first-child').first().text().trim();
                        cyclists.push({ id: `c_${i}`, name, team, bib });
              });
      }

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
// ROTA: Buscar resultado geral (GC) atual
// GET /api/results?race=tour-de-france/2025
// ──────────────────────────────────────────────
app.get('/api/results', async (req, res) => {
    let { race } = req.query;
    if (!race) return res.status(400).json({ error: 'Parâmetro "race" obrigatório.' });

          // Normalizar: remover /startlist do final se vier
          race = race.replace(/\/startlist\/?$/, '');

          try {
                const url = `https://www.procyclingstats.com/race/${race}/result`;
                console.log('Fetching results:', url);

      const { data } = await axios.get(url, { headers: HEADERS, timeout: 15000 });
                const $ = cheerio.load(data);
                const top20 = [];

      // Tabela de resultados do PCS
      $('table.basic tbody tr').each((i, el) => {
              if (i >= 20) return false;
              const tds = $(el).find('td');
              const pos = $(tds[0]).text().trim();
              const nameEl = $(el).find('a[href*="/rider/"]').first();
              const name = nameEl.text().trim();
              if (!name) return;
              const teamEl = $(el).find('a[href*="/team/"]').first();
              const team = teamEl.text().trim();
              const time = $(tds).last().text().trim();
              top20.push({ pos: parseInt(pos) || i + 1, name, team, time });
      });

      // Camisolas
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
// ROTA: Health check
// ──────────────────────────────────────────────
app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', version: '1.1.0', timestamp: new Date().toISOString() });
});

// ──────────────────────────────────────────────
// Fallback → serve o HTML principal
// ──────────────────────────────────────────────
app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
    console.log(`VeloAposta server a correr em http://localhost:${PORT}`);
});
