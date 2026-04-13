from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import requests
from bs4 import BeautifulSoup

app = Flask(__name__, static_folder='public')
CORS(app)

FC_BASE = "https://firstcycling.com"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Referer': 'https://firstcycling.com/',
}

# ── Corridas conhecidas (nome → id no FirstCycling) ──────────────
KNOWN_RACES = {
    'tour-de-france':       17,
    'giro-d-italia':        13,
    'vuelta-a-espana':      23,
    'paris-roubaix':         8,
    'milan-san-remo':        1,
    'milano-sanremo':        1,
    'liege-bastogne-liege': 11,
    'il-lombardia':         19,
    'tour-of-flanders':      9,
    'amstel-gold-race':      9,
    'la-fleche-wallonne':   10,
    'strade-bianche':      386,
    'paris-nice':            2,
    'tirreno-adriatico':    12,
    'criterium-du-dauphine':28,
    'tour-de-suisse':       16,
    'volta-a-catalunya':    14,
    'country-basque':       36,
    'volta-ao-algarve':     16,
    'volta-a-portugal':    525,
}


def fc_get(params):
    """GET ao FirstCycling com os parâmetros dados."""
    resp = requests.get(f"{FC_BASE}/race.php", params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')


def race_id_from_pcs(pcs_id):
    """Converte PCS race id (ex: paris-roubaix/2026) para FC race id."""
    slug = pcs_id.split('/')[0].lower().strip()
    if slug in KNOWN_RACES:
        return KNOWN_RACES[slug]
    # Tenta match parcial
    for key, val in KNOWN_RACES.items():
        if key in slug or slug in key:
            return val
    return None


# ──────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')


@app.get('/api/health')
def health():
    return jsonify({'status': 'ok', 'version': '5.0.0', 'engine': 'firstcycling.com'})


# ──────────────────────────────────────────────
#  Startlist
#  GET /api/startlist?race=paris-roubaix/2026
# ──────────────────────────────────────────────
@app.get('/api/startlist')
def get_startlist():
    pcs_id = _clean_race(request.args.get('race', ''))
    if not pcs_id:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    parts = pcs_id.split('/')
    slug = parts[0]
    year = parts[1] if len(parts) > 1 else '2026'

    fc_id = race_id_from_pcs(slug)
    if not fc_id:
        return jsonify({'error': f'Corrida "{slug}" não encontrada. Verifica o Race ID ou adiciona ao mapa de corridas.'}), 404

    try:
        # k=start = página de startlist no FirstCycling
        soup = fc_get({'r': fc_id, 'y': year, 'k': 'start'})
        cyclists = _parse_startlist(soup)

        if not cyclists:
            return jsonify({'error': 'Startlist vazia ou ainda não disponível.'}), 404

        return jsonify({'race': pcs_id, 'fc_id': fc_id, 'count': len(cyclists), 'cyclists': cyclists})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar startlist: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Resultado clássica (1 dia)
#  GET /api/oneday?race=paris-roubaix/2026
# ──────────────────────────────────────────────
@app.get('/api/oneday')
def get_oneday():
    pcs_id = _clean_race(request.args.get('race', ''))
    if not pcs_id:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    parts = pcs_id.split('/')
    slug = parts[0]
    year = parts[1] if len(parts) > 1 else '2026'

    fc_id = race_id_from_pcs(slug)
    if not fc_id:
        return jsonify({'error': f'Corrida "{slug}" não encontrada.'}), 404

    try:
        # k=8 = resultado da corrida no FirstCycling
        soup = fc_get({'r': fc_id, 'y': year, 'k': 8})
        top20 = _parse_results(soup)

        if not top20:
            return jsonify({'error': 'Resultado ainda não disponível.'}), 404

        return jsonify({'race': pcs_id, 'top20': top20})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar resultado: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  GC após etapa de uma volta
#  GET /api/gc?race=tour-de-france/2025&stage=10
#  stage=latest para etapa mais recente
# ──────────────────────────────────────────────
@app.get('/api/gc')
def get_gc():
    pcs_id = _clean_race(request.args.get('race', ''))
    stage_num = request.args.get('stage', 'latest').strip()
    if not pcs_id:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    parts = pcs_id.split('/')
    slug = parts[0]
    year = parts[1] if len(parts) > 1 else '2026'

    fc_id = race_id_from_pcs(slug)
    if not fc_id:
        return jsonify({'error': f'Corrida "{slug}" não encontrada.'}), 404

    try:
        if stage_num == 'latest':
            # Busca página de stages para descobrir a última
            stage_num = _find_latest_stage_fc(fc_id, year)
            if not stage_num:
                return jsonify({'error': 'Não foi possível determinar a etapa mais recente.'}), 404

        # No FirstCycling, GC de uma etapa: k=gc&e=STAGE_NUM
        soup = fc_get({'r': fc_id, 'y': year, 'k': 'gc', 'e': stage_num})
        top20 = _parse_results(soup)

        if not top20:
            # Fallback: tenta resultado geral
            soup = fc_get({'r': fc_id, 'y': year, 'k': 8})
            top20 = _parse_results(soup)

        return jsonify({'race': pcs_id, 'stage': stage_num, 'top20': top20, 'jerseys': {}})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar GC: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Mapa de IDs conhecidos (para referência no Admin)
#  GET /api/race-ids
# ──────────────────────────────────────────────
@app.get('/api/race-ids')
def get_race_ids():
    return jsonify({
        'info': 'IDs das corridas no FirstCycling (usa o slug do PCS como Race ID)',
        'races': [{'pcs_slug': k, 'fc_id': v} for k, v in KNOWN_RACES.items()]
    })


# ──────────────────────────────────────────────
#  HELPERS — parsing FirstCycling
# ──────────────────────────────────────────────
def _parse_startlist(soup):
    """Extrai ciclistas da página de startlist do FirstCycling."""
    cyclists = []
    seen = set()

    # FirstCycling startlist: tabela com colunas Nº, Ciclista, Equipa, País
    table = soup.find('table')
    if table:
        rows = table.find_all('tr')
        current_team = ''
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue

            # Linha de cabeçalho de equipa
            if len(cells) == 1 and row.find('b'):
                current_team = cells[0].get_text(strip=True)
                continue

            # Linha de ciclista
            rider_a = row.select_one('a[href*="rider.php"]')
            if rider_a:
                name = _title(rider_a.get_text(strip=True))
                if name and name not in seen:
                    seen.add(name)
                    # Número dorsal (primeira célula)
                    number = cells[0].get_text(strip=True) if cells else ''
                    # Equipa (pode estar na linha ou na variável atual)
                    team_a = row.select_one('a[href*="team.php"]')
                    team = team_a.get_text(strip=True) if team_a else current_team
                    cyclists.append({
                        'id': f'c_{len(cyclists)}',
                        'name': name,
                        'team': team,
                        'nationality': '',
                        'number': number if number.isdigit() else None,
                    })

    return cyclists


def _parse_results(soup):
    """Extrai top-20 de uma página de resultados do FirstCycling."""
    top20 = []
    table = soup.find('table')
    if not table:
        return top20

    for row in table.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) < 3:
            continue
        pos_text = cells[0].get_text(strip=True)
        if not pos_text or not pos_text.replace('.', '').isdigit():
            continue
        pos = int(pos_text.replace('.', ''))
        if pos > 20:
            break

        rider_a = row.select_one('a[href*="rider.php"]')
        team_a = row.select_one('a[href*="team.php"]')
        if not rider_a:
            continue

        time_text = cells[-1].get_text(strip=True)
        top20.append({
            'pos': pos,
            'name': _title(rider_a.get_text(strip=True)),
            'team': team_a.get_text(strip=True) if team_a else '',
            'time': time_text,
        })

    return top20


def _find_latest_stage_fc(fc_id, year):
    """Descobre a última etapa disputada no FirstCycling."""
    try:
        from datetime import date
        soup = fc_get({'r': fc_id, 'y': year})
        today = date.today()
        latest = None
        # Procura links de etapas
        for a in soup.select('a[href*="e="]'):
            href = a.get('href', '')
            import re
            m = re.search(r'e=(\d+)', href)
            if m:
                # Tenta ler data do texto próximo
                parent_text = a.find_parent().get_text() if a.find_parent() else ''
                date_m = re.search(r'(\d{2})[./](\d{2})', parent_text)
                if date_m:
                    try:
                        d, mo = int(date_m.group(1)), int(date_m.group(2))
                        if date(int(year), mo, d) <= today:
                            latest = m.group(1)
                    except Exception:
                        latest = m.group(1)
                else:
                    latest = m.group(1)
        return latest
    except Exception:
        return None


def _clean_race(race):
    race = race.strip()
    if 'procyclingstats.com/race/' in race:
        race = race.split('procyclingstats.com/race/')[-1]
    if race.startswith('race/'):
        race = race[len('race/'):]
    for suffix in ['/startlist', '/overview', '/gc', '/result', '/route']:
        if race.endswith(suffix):
            race = race[:-len(suffix)]
    return race


def _title(text):
    return ' '.join(w.capitalize() for w in text.strip().split())


# ──────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f"✅ VeloAposta v5 (FirstCycling) a correr em http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
