from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import requests
import cloudscraper

app = Flask(__name__, static_folder='public')
CORS(app)

# ──────────────────────────────────────────────
#  Patch: substitui requests por cloudscraper
#  para contornar a proteção Cloudflare do PCS
# ──────────────────────────────────────────────
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)

try:
    import procyclingstats.scraper as pcs_scraper_module

    class CloudSession(requests.Session):
        def get(self, url, **kwargs):
            kwargs.pop('timeout', None)
            return scraper.get(url, **kwargs)

    class PatchedRequests:
        Session           = CloudSession
        RequestException  = requests.RequestException
        exceptions        = requests.exceptions
        HTTPError         = requests.HTTPError
        ConnectionError   = requests.ConnectionError
        Timeout           = requests.Timeout

        @staticmethod
        def get(url, **kwargs):
            kwargs.pop('timeout', None)
            return scraper.get(url, **kwargs)

    pcs_scraper_module.requests = PatchedRequests()

    from procyclingstats import RaceStartlist, Stage, Race
    PCS_AVAILABLE = True
    print("✅ procyclingstats + cloudscraper prontos")
except Exception as e:
    PCS_AVAILABLE = False
    print(f"⚠ Erro ao inicializar procyclingstats: {e}")


# ──────────────────────────────────────────────
#  Serve o frontend (index.html)
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
    return jsonify({
        'status': 'ok',
        'version': '3.2.0',
        'engine': 'procyclingstats + cloudscraper',
        'pcs_available': PCS_AVAILABLE
    })


# ──────────────────────────────────────────────
#  Startlist
#  GET /api/startlist?race=paris-roubaix/2026
# ──────────────────────────────────────────────
@app.get('/api/startlist')
def get_startlist():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não disponível.'}), 500

    race = request.args.get('race', '').strip()
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório. Ex: paris-roubaix/2026'}), 400

    for suffix in ['/startlist/startlist', '/startlist', '/overview', '/gc', '/result']:
        if race.endswith(suffix):
            race = race[:-len(suffix)]

    try:
        sl = RaceStartlist(f"race/{race}/startlist")
        raw = sl.startlist()

        cyclists = []
        for r in raw:
            name = r.get('rider_name', '')
            name = ' '.join(w.capitalize() for w in name.split())
            cyclists.append({
                'id': r.get('rider_url', '').replace('rider/', ''),
                'name': name,
                'team': r.get('team_name', ''),
                'nationality': r.get('nationality', ''),
                'number': r.get('rider_number'),
            })

        return jsonify({'race': race, 'count': len(cyclists), 'cyclists': cyclists})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar startlist: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  GC (Classificação Geral após etapa)
#  GET /api/gc?race=tour-de-france/2025&stage=10
#  stage=latest para etapa mais recente
# ──────────────────────────────────────────────
@app.get('/api/gc')
def get_gc():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não disponível.'}), 500

    race = request.args.get('race', '').strip()
    stage_num = request.args.get('stage', 'latest').strip()
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    try:
        if stage_num == 'latest':
            stage_num = _find_latest_stage(race)
            if stage_num is None:
                return jsonify({'error': 'Não foi possível determinar a etapa mais recente.'}), 404

        parsed = Stage(f"race/{race}/stage-{stage_num}").parse()
        return jsonify({
            'race': race,
            'stage': stage_num,
            'date': str(parsed.get('date', '')),
            'departure': parsed.get('departure', ''),
            'arrival': parsed.get('arrival', ''),
            'top20': _parse_riders(parsed.get('gc', [])),
            'jerseys': _extract_jerseys(parsed),
        })

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar GC: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Resultado clássica (1 dia)
#  GET /api/oneday?race=paris-roubaix/2026
# ──────────────────────────────────────────────
@app.get('/api/oneday')
def get_oneday():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não disponível.'}), 500

    race = request.args.get('race', '').strip()
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    for suffix in ['/result', '/startlist', '/overview']:
        if race.endswith(suffix):
            race = race[:-len(suffix)]

    try:
        parsed = Stage(f"race/{race}/result").parse()
        result_raw = parsed.get('stage', parsed.get('result', []))
        return jsonify({
            'race': race,
            'date': str(parsed.get('date', '')),
            'top20': _parse_riders(result_raw[:20]),
        })

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar resultado: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Lista de etapas
#  GET /api/stages?race=tour-de-france/2025
# ──────────────────────────────────────────────
@app.get('/api/stages')
def get_stages():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não disponível.'}), 500

    race = request.args.get('race', '').strip()
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    try:
        stages_raw = Race(f"race/{race}/overview").stages()
        stages = [{
            'num': _extract_stage_num(s.get('stage_url', '')),
            'url': s.get('stage_url', ''),
            'date': str(s.get('date', '')),
            'departure': s.get('departure', ''),
            'arrival': s.get('arrival', ''),
            'distance': s.get('distance'),
            'stage_type': s.get('stage_type', ''),
        } for s in stages_raw]

        return jsonify({'race': race, 'count': len(stages), 'stages': stages})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar etapas: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def _parse_riders(raw):
    result = []
    for entry in raw[:20]:
        name = entry.get('rider_name', '')
        name = ' '.join(w.capitalize() for w in name.split())
        result.append({
            'pos': entry.get('rank'),
            'name': name,
            'team': entry.get('team_name', ''),
            'time': _format_time(entry.get('time')),
            'nationality': entry.get('nationality', ''),
        })
    return result


def _format_time(t):
    if t is None:
        return ''
    try:
        total = int(t.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"+{m}:{s:02d}"
    except Exception:
        return str(t)


def _extract_jerseys(parsed):
    jerseys = {}
    gc_raw = parsed.get('gc', [])
    if gc_raw:
        name = gc_raw[0].get('rider_name', '')
        jerseys['gc'] = ' '.join(w.capitalize() for w in name.split())
    for key, mapped in [('gc_jersey','gc'), ('points_jersey','points'),
                        ('kom_jersey','mountain'), ('youth_jersey','youth')]:
        val = parsed.get(key)
        if val:
            rider = val if isinstance(val, str) else val.get('rider_name', '')
            jerseys[mapped] = ' '.join(w.capitalize() for w in rider.split())
    return jerseys


def _find_latest_stage(race):
    from datetime import date
    try:
        stages = Race(f"race/{race}/overview").stages()
        today = date.today()
        latest = None
        for s in stages:
            d = s.get('date')
            if d:
                try:
                    if date.fromisoformat(str(d)[:10]) <= today:
                        latest = _extract_stage_num(s.get('stage_url', ''))
                except Exception:
                    pass
        return latest
    except Exception:
        return None


def _extract_stage_num(stage_url):
    for part in reversed(stage_url.rstrip('/').split('/')):
        if part.startswith('stage-'):
            return part.replace('stage-', '')
    return None


# ──────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f"✅ VeloAposta a correr em http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
