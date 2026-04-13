from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import re
import cloudscraper
from bs4 import BeautifulSoup

app = Flask(__name__, static_folder='public')
CORS(app)

# ──────────────────────────────────────────────
#  Cloudscraper — contorna Cloudflare do PCS
# ──────────────────────────────────────────────
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)
PCS_BASE = "https://www.procyclingstats.com"


def pcs_get(path):
    """Faz GET ao PCS e devolve BeautifulSoup."""
    url = f"{PCS_BASE}/{path}"
    print(f"  → GET {url}")
    resp = scraper.get(url, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')


# ──────────────────────────────────────────────
#  Serve o frontend
# ──────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')


# ──────────────────────────────────────────────
#  Health check
# ──────────────────────────────────────────────
@app.get('/api/health')
def health():
    return jsonify({'status': 'ok', 'version': '4.0.0', 'engine': 'cloudscraper + bs4'})


# ──────────────────────────────────────────────
#  Startlist
#  GET /api/startlist?race=paris-roubaix/2026
# ──────────────────────────────────────────────
@app.get('/api/startlist')
def get_startlist():
    race = _clean_race(request.args.get('race', ''))
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400
    try:
        soup = pcs_get(f"race/{race}/startlist")
        cyclists = []

        # PCS startlist: lista de riders dentro de divs com classe "ridersCont"
        # Cada rider tem um link <a href="/rider/...">NOME APELIDO</a>
        # e a equipa está no elemento pai ou num span próximo
        rider_links = soup.select('ul.startlist li a[href*="/rider/"]')

        if not rider_links:
            # Fallback: tabela
            rows = soup.select('table.basic tbody tr')
            for i, row in enumerate(rows):
                name_el = row.select_one('a[href*="/rider/"]')
                team_el = row.select_one('a[href*="/team/"]')
                if not name_el:
                    continue
                cyclists.append({
                    'id': f'c_{i}',
                    'name': _title(name_el.text),
                    'team': team_el.text.strip() if team_el else '',
                    'nationality': '',
                    'number': None,
                })
        else:
            seen = set()
            for i, a in enumerate(rider_links):
                name = _title(a.text)
                if not name or name in seen:
                    continue
                seen.add(name)
                # Equipa: texto do li pai ou elemento vizinho
                li = a.find_parent('li')
                team = ''
                if li:
                    team_a = li.select_one('a[href*="/team/"]')
                    team = team_a.text.strip() if team_a else ''
                    if not team:
                        spans = li.find_all('span')
                        if len(spans) > 1:
                            team = spans[-1].text.strip()
                cyclists.append({
                    'id': f'c_{i}',
                    'name': name,
                    'team': team,
                    'nationality': '',
                    'number': None,
                })

        if not cyclists:
            return jsonify({'error': 'Startlist vazia ou formato não reconhecido.'}), 404

        return jsonify({'race': race, 'count': len(cyclists), 'cyclists': cyclists})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar startlist: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  GC após etapa
#  GET /api/gc?race=tour-de-france/2025&stage=10
#  stage=latest para etapa mais recente
# ──────────────────────────────────────────────
@app.get('/api/gc')
def get_gc():
    race = _clean_race(request.args.get('race', ''))
    stage_num = request.args.get('stage', 'latest').strip()
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400
    try:
        if stage_num == 'latest':
            stage_num = _find_latest_stage(race)
            if not stage_num:
                return jsonify({'error': 'Etapa mais recente não encontrada.'}), 404

        soup = pcs_get(f"race/{race}/stage-{stage_num}/gc")
        top20, jerseys = _parse_gc_page(soup)

        return jsonify({
            'race': race, 'stage': stage_num,
            'top20': top20, 'jerseys': jerseys,
        })
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar GC: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Resultado clássica (1 dia)
#  GET /api/oneday?race=paris-roubaix/2026
# ──────────────────────────────────────────────
@app.get('/api/oneday')
def get_oneday():
    race = _clean_race(request.args.get('race', ''))
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400
    try:
        soup = pcs_get(f"race/{race}/result")
        top20 = _parse_result_table(soup)
        return jsonify({'race': race, 'top20': top20})
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar resultado: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Lista de etapas
#  GET /api/stages?race=tour-de-france/2025
# ──────────────────────────────────────────────
@app.get('/api/stages')
def get_stages():
    race = _clean_race(request.args.get('race', ''))
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400
    try:
        soup = pcs_get(f"race/{race}/overview")
        stages = []
        for a in soup.select('a[href*="/stage-"]'):
            href = a.get('href', '')
            num = _extract_stage_num(href)
            if num and not any(s['num'] == num for s in stages):
                stages.append({'num': num, 'url': href, 'name': a.text.strip()})
        return jsonify({'race': race, 'count': len(stages), 'stages': stages})
    except Exception as e:
        return jsonify({'error': f'Erro ao buscar etapas: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  HELPERS — parsing
# ──────────────────────────────────────────────
def _parse_gc_page(soup):
    """Extrai top-20 GC e camisolas de uma página de GC do PCS."""
    top20 = []
    jerseys = {}

    rows = soup.select('table.basic tbody tr')
    for row in rows[:20]:
        tds = row.find_all('td')
        if len(tds) < 3:
            continue
        pos_text = tds[0].text.strip()
        pos = int(pos_text) if pos_text.isdigit() else len(top20) + 1
        name_el = row.select_one('a[href*="/rider/"]')
        team_el = row.select_one('a[href*="/team/"]')
        if not name_el:
            continue
        time_text = tds[-1].text.strip()
        top20.append({
            'pos': pos,
            'name': _title(name_el.text),
            'team': team_el.text.strip() if team_el else '',
            'time': time_text,
        })

    # Camisolas — secção de jersey leaders no topo da página
    for div in soup.select('.jersey, .classification, [class*="jersey"]'):
        cls = ' '.join(div.get('class', []))
        rider_a = div.select_one('a[href*="/rider/"]')
        if not rider_a:
            continue
        name = _title(rider_a.text)
        if 'point' in cls or 'green' in cls:
            jerseys['points'] = name
        elif 'mountain' in cls or 'polka' in cls or 'kom' in cls:
            jerseys['mountain'] = name
        elif 'youth' in cls or 'white' in cls:
            jerseys['youth'] = name

    # Líder do GC = camisola amarela
    if top20 and 'gc' not in jerseys:
        jerseys['gc'] = top20[0]['name']

    return top20, jerseys


def _parse_result_table(soup):
    """Extrai top-20 de uma tabela de resultados genérica."""
    top20 = []
    rows = soup.select('table.basic tbody tr')
    for row in rows[:20]:
        tds = row.find_all('td')
        if len(tds) < 2:
            continue
        pos_text = tds[0].text.strip()
        pos = int(pos_text) if pos_text.isdigit() else len(top20) + 1
        name_el = row.select_one('a[href*="/rider/"]')
        team_el = row.select_one('a[href*="/team/"]')
        if not name_el:
            continue
        time_text = tds[-1].text.strip()
        top20.append({
            'pos': pos,
            'name': _title(name_el.text),
            'team': team_el.text.strip() if team_el else '',
            'time': time_text,
        })
    return top20


def _find_latest_stage(race):
    """Descobre o número da última etapa já disputada."""
    from datetime import date
    try:
        soup = pcs_get(f"race/{race}/overview")
        today = date.today()
        latest = None
        for a in soup.select('a[href*="/stage-"]'):
            href = a.get('href', '')
            num = _extract_stage_num(href)
            if not num:
                continue
            # Tenta encontrar a data no texto próximo
            parent = a.find_parent()
            text = parent.text if parent else ''
            date_match = re.search(r'(\d{2})[./](\d{2})', text)
            if date_match:
                try:
                    m, d = int(date_match.group(2)), int(date_match.group(1))
                    y = today.year
                    if date(y, m, d) <= today:
                        latest = num
                except Exception:
                    pass
            else:
                latest = num  # sem data, assume que já passou
        return latest
    except Exception:
        return None


def _clean_race(race):
    """Remove sufixos de URL desnecessários."""
    race = race.strip()
    for suffix in ['/startlist', '/overview', '/gc', '/result', '/route']:
        if race.endswith(suffix):
            race = race[:-len(suffix)]
    return race


def _extract_stage_num(url):
    for part in reversed(url.rstrip('/').split('/')):
        if part.startswith('stage-'):
            return part.replace('stage-', '')
    return None


def _title(text):
    """Converte APELIDO Nome para Nome Apelido (title case)."""
    return ' '.join(w.capitalize() for w in text.strip().split())


# ──────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f"✅ VeloAposta v4 a correr em http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
