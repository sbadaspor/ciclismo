from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
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

# Monkey-patch para que o procyclingstats use o nosso scraper
try:
    import procyclingstats.scraper as pcs_scraper_module
    import requests

    class PatchedSession(requests.Session):
        def get(self, url, **kwargs):
            kwargs.pop('timeout', None)
            resp = scraper.get(url, **kwargs)
            return resp

    pcs_scraper_module.requests = type('FakeRequests', (), {
        'get': lambda url, **kw: scraper.get(url, **kw),
        'Session': PatchedSession,
    })()

    from procyclingstats import RaceStartlist, Stage, Race
    PCS_AVAILABLE = True
    print("✅ procyclingstats + cloudscraper prontos")
except ImportError as e:
    PCS_AVAILABLE = False
    print(f"⚠ Erro ao importar procyclingstats: {e}")


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
        'version': '3.1.0',
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

    # Normaliza — remove sufixos desnecessários se o user colou o URL completo
    for suffix in ['/startlist/startlist', '/startlist', '/overview', '/gc', '/result']:
        if race.endswith(suffix):
            race = race[:-len(suffix)]

    try:
        url = f"race/{race}/startlist"
        sl = RaceStartlist(url)
        raw = sl.startlist()

        cyclists = []
        for r in raw:
            name = r.get('rider_name', '')
            # PCS devolve nomes em MAIÚSCULAS — converte para Title Case
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
#  GC (Classificação Geral)
#  GET /api/gc?race=tour-de-france/2025&stage=10
#  stage=latest para a etapa mais recente
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

        url = f"race/{race}/stage-{stage_num}"
        stage = Stage(url)
        parsed = stage.parse()

        top20 = _parse_gc(parsed.get('gc', []))
        jerseys = _extract_jerseys(parsed)

        return jsonify({
            'race': race,
            'stage': stage_num,
            'date': str(parsed.get('date', '')),
            'departure': parsed.get('departure', ''),
            'arrival': parsed.get('arrival', ''),
            'top20': top20,
            'jerseys': jerseys,
        })

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar GC: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  Resultado de clássica (1 dia)
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
        url = f"race/{race}/result"
        stage = Stage(url)
        parsed = stage.parse()

        result_raw = parsed.get('stage', parsed.get('result', []))
        top20 = []
        for entry in result_raw[:20]:
            name = entry.get('rider_name', '')
            name = ' '.join(w.capitalize() for w in name.split())
            top20.append({
                'pos': entry.get('rank'),
                'name': name,
                'team': entry.get('team_name', ''),
                'time': _format_time(entry.get('time')),
                'nationality': entry.get('nationality', ''),
            })

        return jsonify({'race': race, 'date': str(parsed.get('date', '')), 'top20': top20})

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
        url = f"race/{race}/overview"
        r = Race(url)
        stages_raw = r.stages()

        stages = []
        for s in stages_raw:
            num = _extract_stage_num(s.get('stage_url', ''))
            stages.append({
                'num': num,
                'url': s.get('stage_url', ''),
                'date': str(s.get('date', '')),
                'departure': s.get('departure', ''),
                'arrival': s.get('arrival', ''),
                'distance': s.get('distance'),
                'stage_type': s.get('stage_type', ''),
            })

        return jsonify({'race': race, 'count': len(stages), 'stages': stages})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar etapas: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def _parse_gc(gc_raw):
    top20 = []
    for entry in gc_raw[:20]:
        name = entry.get('rider_name', '')
        name = ' '.join(w.capitalize() for w in name.split())
        top20.append({
            'pos': entry.get('rank'),
            'name': name,
            'team': entry.get('team_name', ''),
            'time': _format_time(entry.get('time')),
            'nationality': entry.get('nationality', ''),
        })
    return top20


def _format_time(t):
    if t is None:
        return ''
    try:
        total = int(t.total_seconds())
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"+{m}:{s:02d}"
    except Exception:
        return str(t)


def _extract_jerseys(parsed):
    jerseys = {}
    gc_raw = parsed.get('gc', [])
    if gc_raw:
        name = gc_raw[0].get('rider_name', '')
        jerseys['gc'] = ' '.join(w.capitalize() for w in name.split())
    for key, mapped in [('gc_jersey','gc'),('points_jersey','points'),('kom_jersey','mountain'),('youth_jersey','youth')]:
        val = parsed.get(key)
        if val:
            rider = val if isinstance(val, str) else val.get('rider_name', '')
            jerseys[mapped] = ' '.join(w.capitalize() for w in rider.split())
    return jerseys


def _find_latest_stage(race):
    try:
        from datetime import date
        url = f"race/{race}/overview"
        r = Race(url)
        stages = r.stages()
        today = date.today()
        latest = None
        for s in stages:
            d = s.get('date')
            if d:
                try:
                    stage_date = date.fromisoformat(str(d)[:10])
                    if stage_date <= today:
                        latest = _extract_stage_num(s.get('stage_url', ''))
                except Exception:
                    pass
        return latest
    except Exception:
        return None


def _extract_stage_num(stage_url):
    parts = stage_url.rstrip('/').split('/')
    for part in reversed(parts):
        if part.startswith('stage-'):
            return part.replace('stage-', '')
    return None


# ──────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f"✅ VeloAposta a correr em http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
