const express = require('express');
const cors = require('cors');
const axios = require('axios');
const cheerio = require('cheerio');
const path = require('path');
const https = require('https');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Serve os ficheiros estáticos (o teu HTML)
app.use(express.static(path.join(__dirname, 'public')));

// ──────────────────────────────────────────────
// Lista de proxies gratuitos para contornar
// o bloqueio 403 do PCS em IPs de datacenter
// ──────────────────────────────────────────────
const PROXY_URLS = [
        (url) => `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`,
        (url) => `https://corsproxy.io/?${encodeURIComponent(url)}`,
        (url) => `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(url)}`,
      ];

const HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
};

// ──────────────────────────────────────────────
// Fetch direto (sem proxy)
// ──────────────────────────────────────────────
const axiosDirect = axios.create({
        httpsAgent: new https.Agent({ rejectUnauthorized: false }),
        timeout: 15000,
        headers: HEADERS,
});

// ──────────────────────────────────────────────
// Tentar fetch: primeiro direto, depois proxies
// ──────────────────────────────────────────────
async function fetchHtml(targetUrl) {
        // 1. Tentar direto
  try {
            const res = await axiosDirect.get(targetUrl);
            if (res.status === 200) {
                        console.log(`Direto OK: ${targetUrl}`);
                        return res.data;
            }
  } catch (err) {
            console.warn(`Direto falhou (${err.response?.status || err.message}): ${targetUrl}`);
  }

  // 2. Tentar cada proxy
  for (let i = 0; i < PROXY_URLS.length; i++) {
            const proxyUrl = PROXY_URLS[i](targetUrl);
            try {
                        const res = await axios.get(proxyUrl, { timeout: 15000 });
                        if (res.status === 200 && res.data && typeof res.data === 'string' && res.data.length > 100) {
                                      console.log(`Proxy ${i + 1} OK: ${proxyUrl}`);
                                      return res.data;
                        }
            } catch (err) {
                        console.warn(`Proxy ${i + 1} falhou: ${err.message}`);
            }
  }

  throw new Error('Todos os métodos de fetch falharam (bloqueio 403 do PCS).');
}

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

          const data = await fetchHtml(url);
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

          // Fallback: seletores antigos
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
                    res.status(503).json({ error: err.message });
          }
});

// ──────────────────────────────────────────────
// ROTA: Buscar resultado geral atual
// GET /api/results?race=tour-de-france/2025
// ──────────────────────────────────────────────
app.get('/api/results', async (req, res) => {
        let { race } = req.query;
        if (!race) return res.status(400).json({ error: 'Parâmetro "race" obrigatório.' });

          race = race.replace(/\/startlist\/?$/, '');

          try {
                    const url = `https://www.procyclingstats.com/race/${race}/result`;
                    console.log('Fetching results:', url);

          const data = await fetchHtml(url);
                    const $ = cheerio.load(data);
                    const top20 = [];

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
                    res.status(503).json({ error: err.message });
          }
});

// ──────────────────────────────────────────────
// ROTA: Health check
// ──────────────────────────────────────────────
app.get('/api/health', (req, res) => {
        res.json({ status: 'ok', version: '1.3.0', timestamp: new Date().toISOString() });
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
