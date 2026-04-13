from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os

app = Flask(__name__, static_folder='public')
CORS(app)

# ──────────────────────────────────────────────
#  Import procyclingstats — instalado via pip
# ──────────────────────────────────────────────
try:
    from procyclingstats import RaceStartlist, Stage, Race
    PCS_AVAILABLE = True
except ImportError:
    PCS_AVAILABLE = False
    print("⚠ procyclingstats não instalado. Corre: pip install procyclingstats")


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
#  ROTA: Health check
#  GET /api/health
# ──────────────────────────────────────────────
@app.get('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'version': '3.0.0',
        'engine': 'procyclingstats',
        'pcs_available': PCS_AVAILABLE
    })


# ──────────────────────────────────────────────
#  ROTA: Startlist de uma corrida
#  GET /api/startlist?race=tour-de-france/2025
#
#  Exemplo de resposta:
#  { cyclists: [ { name, team, nationality, number } ] }
# ──────────────────────────────────────────────
@app.get('/api/startlist')
def get_startlist():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não instalado no servidor.'}), 500

    race = request.args.get('race')
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório. Ex: tour-de-france/2025'}), 400

    try:
        url = f"race/{race}/startlist"
        sl = RaceStartlist(url)
        raw = sl.startlist()

        cyclists = []
        for r in raw:
            cyclists.append({
                'id': r.get('rider_url', '').replace('rider/', ''),
                'name': r.get('rider_name', '').title(),
                'team': r.get('team_name', ''),
                'nationality': r.get('nationality', ''),
                'number': r.get('rider_number'),
            })

        return jsonify({'race': race, 'count': len(cyclists), 'cyclists': cyclists})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar startlist: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  ROTA: Resultado GC atual (classificação geral)
#  GET /api/gc?race=tour-de-france/2025&stage=10
#
#  Busca o GC após a etapa indicada.
#  Se stage=latest, usa a etapa mais recente.
#
#  Exemplo de resposta:
#  { top20, jerseys: { gc, points, mountain, youth } }
# ──────────────────────────────────────────────
@app.get('/api/gc')
def get_gc():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não instalado no servidor.'}), 500

    race = request.args.get('race')
    stage_num = request.args.get('stage', 'latest')

    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório. Ex: tour-de-france/2025'}), 400

    try:
        # Se stage=latest, determina automaticamente a última etapa disponível
        if stage_num == 'latest':
            stage_num = _find_latest_stage(race)
            if stage_num is None:
                return jsonify({'error': 'Não foi possível determinar a etapa mais recente.'}), 404

        url = f"race/{race}/stage-{stage_num}"
        stage = Stage(url)
        parsed = stage.parse()

        # GC (classificação geral) — lista de ciclistas com rank
        gc_raw = parsed.get('gc', [])
        top20 = []
        for entry in gc_raw[:20]:
            top20.append({
                'pos': entry.get('rank'),
                'name': entry.get('rider_name', '').title(),
                'team': entry.get('team_name', ''),
                'time': _format_time(entry.get('time')),
                'nationality': entry.get('nationality', ''),
            })

        # Camisolas — o Stage pode ter info de jersey leaders
        jerseys = _extract_jerseys(parsed)

        return jsonify({
            'race': race,
            'stage': stage_num,
            'date': parsed.get('date'),
            'departure': parsed.get('departure'),
            'arrival': parsed.get('arrival'),
            'top20': top20,
            'jerseys': jerseys,
        })

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar GC: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  ROTA: Resultado de uma etapa específica
#  GET /api/stage?race=tour-de-france/2025&stage=10
#
#  Retorna vencedor da etapa + GC atualizado
# ──────────────────────────────────────────────
@app.get('/api/stage')
def get_stage():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não instalado no servidor.'}), 500

    race = request.args.get('race')
    stage_num = request.args.get('stage')

    if not race or not stage_num:
        return jsonify({'error': 'Parâmetros "race" e "stage" obrigatórios.'}), 400

    try:
        url = f"race/{race}/stage-{stage_num}"
        stage = Stage(url)
        parsed = stage.parse()

        # Resultado da etapa (vencedor)
        stage_results_raw = parsed.get('stage', [])
        stage_result = []
        for entry in stage_results_raw[:10]:
            stage_result.append({
                'pos': entry.get('rank'),
                'name': entry.get('rider_name', '').title(),
                'team': entry.get('team_name', ''),
                'time': _format_time(entry.get('time')),
            })

        # GC após a etapa
        gc_raw = parsed.get('gc', [])
        top20 = []
        for entry in gc_raw[:20]:
            top20.append({
                'pos': entry.get('rank'),
                'name': entry.get('rider_name', '').title(),
                'team': entry.get('team_name', ''),
                'time': _format_time(entry.get('time')),
                'nationality': entry.get('nationality', ''),
            })

        jerseys = _extract_jerseys(parsed)

        return jsonify({
            'race': race,
            'stage': stage_num,
            'date': parsed.get('date'),
            'departure': parsed.get('departure'),
            'arrival': parsed.get('arrival'),
            'distance': parsed.get('distance'),
            'stage_result': stage_result,
            'top20': top20,
            'jerseys': jerseys,
        })

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar etapa: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  ROTA: Lista de etapas de uma corrida
#  GET /api/stages?race=tour-de-france/2025
# ──────────────────────────────────────────────
@app.get('/api/stages')
def get_stages():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não instalado no servidor.'}), 500

    race = request.args.get('race')
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
                'date': s.get('date'),
                'departure': s.get('departure'),
                'arrival': s.get('arrival'),
                'distance': s.get('distance'),
                'stage_type': s.get('stage_type'),
            })

        return jsonify({'race': race, 'count': len(stages), 'stages': stages})

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar etapas: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  ROTA: Resultado de corrida de 1 dia (clássica)
#  GET /api/oneday?race=milano-sanremo/2025
# ──────────────────────────────────────────────
@app.get('/api/oneday')
def get_oneday():
    if not PCS_AVAILABLE:
        return jsonify({'error': 'procyclingstats não instalado no servidor.'}), 500

    race = request.args.get('race')
    if not race:
        return jsonify({'error': 'Parâmetro "race" obrigatório.'}), 400

    try:
        url = f"race/{race}/result"
        stage = Stage(url)
        parsed = stage.parse()

        result_raw = parsed.get('stage', parsed.get('result', []))
        top20 = []
        for entry in result_raw[:20]:
            top20.append({
                'pos': entry.get('rank'),
                'name': entry.get('rider_name', '').title(),
                'team': entry.get('team_name', ''),
                'time': _format_time(entry.get('time')),
                'nationality': entry.get('nationality', ''),
            })

        return jsonify({
            'race': race,
            'date': parsed.get('date'),
            'top20': top20,
        })

    except Exception as e:
        return jsonify({'error': f'Erro ao buscar resultado: {str(e)}'}), 500


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def _format_time(t):
    """Converte timedelta ou string de tempo para string legível."""
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
    """Tenta extrair portadores de camisolas do resultado da etapa."""
    jerseys = {}
    # O Stage.parse() pode incluir info de jerseys em 'gc_winner', etc.
    # Tenta campos comuns do procyclingstats
    for key in ['gc_jersey', 'points_jersey', 'kom_jersey', 'youth_jersey']:
        val = parsed.get(key)
        if val:
            mapping = {
                'gc_jersey': 'gc',
                'points_jersey': 'points',
                'kom_jersey': 'mountain',
                'youth_jersey': 'youth',
            }
            rider_name = val if isinstance(val, str) else val.get('rider_name', '')
            jerseys[mapping[key]] = rider_name.title() if rider_name else ''

    # Alternativa: primeiro do GC é o líder
    gc_raw = parsed.get('gc', [])
    if gc_raw and 'gc' not in jerseys:
        leader = gc_raw[0]
        jerseys['gc'] = leader.get('rider_name', '').title()

    return jerseys


def _find_latest_stage(race):
    """Tenta descobrir o número da última etapa disputada."""
    try:
        url = f"race/{race}/overview"
        r = Race(url)
        stages = r.stages()
        # Filtra etapas com data passada ou igual a hoje
        from datetime import date
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
    """Extrai número da etapa do URL. Ex: 'race/tour-de-france/2025/stage-10' → '10'"""
    parts = stage_url.rstrip('/').split('/')
    for part in reversed(parts):
        if part.startswith('stage-'):
            return part.replace('stage-', '')
    return None


# ──────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    print(f"✅ VeloAposta (procyclingstats) a correr em http://localhost:{port}")
    print(f"   procyclingstats disponível: {PCS_AVAILABLE}")
    app.run(host='0.0.0.0', port=port, debug=debug)
