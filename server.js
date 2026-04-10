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
// Axios instance que ignora erros de SSL e usa
// headers realistas para evitar bloqueio 403
// ──────────────────────────────────────────────
const axiosInstance = axios.create({
      httpsAgent: new https.Agent({ rejectUnauthorized: false }),
      timeout: 20000,
      maxRedirects: 5,
      headers: {
              'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
              'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
              'Accept-Language': 'en-US,en;q=0.9,pt;q=0.8',
              'Accept-Encoding': 'gzip, deflate, br',
              'Cache-Control': 'max-age=0',
              'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
              'Sec-Ch-Ua-Mobile': '?0',
              'Sec-Ch-Ua-Platform': '"Linux"',
              'Sec-Fetch-Dest': 'document',
              'Sec-Fetch-Mode': 'navigate',
              'Sec-Fetch-Site': 'none',
              'Sec-Fetch-User': '?1',
              'Upgrade-Insecure-Requests': '1',
              'Referer': 'https://www.google.com/',
              'Connection': 'keep-alive',
      },
});

// ──────────────────────────────────────────────
// Função auxiliar: fetch com retry
// ──────────────────────────────────────────────
async function fetchWithRetry(url, retries = 3) {
      for (let i = 0; i < retries; i++) {
              try {
                        const res = await axiosInstance.get(url);
                        return res.data;
              } catch (err) {
                        console.error(`Tentativa ${i + 1} falhou para ${url}: ${err.message}`);
                        if (i < retries - 1) {
                                    await new Promise(r => setTimeout(r, 2000 * (i + 1)));
                        } else {
                                    throw err;
                        }
              }
      }
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

        const data = await fetchWithRetry(url);
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

        // Fallback: seletores alternativos do PCS
        if (cyclists.length === 0) {
                  // Tentar links de riders diretamente
                    const seen = new Set();
                  $('a[href*="/rider/"]').each((i, el) => {
                              const name = $(el).text().trim();
                              if (!name || seen.has(name)) return;
                              // Ignorar links de navegação/menu (muito curtos ou contendo palavras de nav)
                                                       if (name.length < 3 || name.toLowerCase().includes('rider')) return;
                              seen.add(name);
                              const parentLi = $(el).closest('li');
                              const teamLink = parentLi.find('a[href*="/team/"]').first();
                              const team = teamLink.text().trim();
                              cyclists.push({ id: `c_${i}`, name, team, bib: '' });
                  });
        }

        if (cyclists.length === 0) {
                  return res.status(404).json({ error: 'Nenhum ciclista encontrado. Verifica o Race ID.' });
        }

        res.json({ race, count: cyclists.length, cyclists });
          } catch (err) {
                  console.error('Startlist error:', err.message);
                  const status = err.response?.status || 500;
                  res.status(status === 403 ? 503 : 500).json({
                            error: status === 403
                              ? 'O site PCS bloqueou o pedido (403). Tenta novamente em alguns segundos.'
                                        : 'Erro ao buscar startlist: ' + err.message,
                  });
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

        const data = await fetchWithRetry(url);
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
                  res.status(500).json({ error: 'Erro ao buscar resultados: ' + err.message });
          }
});

// ──────────────────────────────────────────────
// ROTA: Health check
// ──────────────────────────────────────────────
app.get('/api/health', (req, res) => {
      res.json({ status: 'ok', version: '1.2.0', timestamp: new Date().toISOString() });
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
