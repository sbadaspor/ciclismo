from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
from first_cycling_api import RaceEdition, Rider

app = Flask(__name__, static_folder='public')
CORS(app)

# ── Mapeamento de Corridas (PCS slug → FC id) ──────────────────
KNOWN_RACES = {
    'tour-de-france': 17, 'giro-d-italia': 13, 'vuelta-a-espana': 23,
    'paris-roubaix': 8, 'milan-san-remo': 1, 'milano-sanremo': 1,
    'liege-bastogne-liege': 11, 'il-lombardia': 19, 'tour-of-flanders': 9,
    'amstel-gold-race': 9, 'la-fleche-wallonne': 10, 'strade-bianche': 386,
    'paris-nice': 2, 'tirreno-adriatico': 12, 'criterium-du-dauphine': 28,
    'tour-de-suisse': 16, 'volta-a-catalunya': 14, 'country-basque': 36,
    'volta-ao-algarve': 16, 'volta-a-portugal': 525,
}

def get_fc_info(pcs_id):
    """Extrai slug e ano do parâmetro 'race'."""
    parts = pcs_id.split('/')
    slug = parts[0].lower().strip()
    year = int(parts[1]) if len(parts) > 1 else 2026
    return KNOWN_RACES.get(slug), year

# ── Rotas de Frontend ──────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

@app.get('/api/health')
def health():
    return jsonify({'status': 'ok', 'version': '6.0.0 (API Mode)'})

# ── API: Startlist ─────────────────────────────────────────────
@app.get('/api/startlist')
def get_startlist():
    race_param = request.args.get('race', '')
    fc_id, year = get_fc_info(race_param)

    if not fc_id:
        return jsonify({'error': 'Corrida não mapeada.'}), 404

    try:
        race = RaceEdition(race_id=fc_id, year=year)
        # Obter startlist e converter DataFrame para lista de dicts
        df = race.startlist().startlist_table
        cyclists = df.to_dict(orient='records')

        return jsonify({
            'race': race_param,
            'fc_id': fc_id,
            'count': len(cyclists),
            'cyclists': cyclists
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── API: Resultado Clássica ou Etapa ──────────────────────────
@app.get('/api/oneday')
def get_oneday():
    race_param = request.args.get('race', '')
    fc_id, year = get_fc_info(race_param)

    try:
        race = RaceEdition(race_id=fc_id, year=year)
        # .results() por defeito traz o resultado final/último
        df = race.results().results_table
        top20 = df.head(20).to_dict(orient='records')

        return jsonify({'race': race_param, 'top20': top20})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── API: Classificação Geral (GC) ──────────────────────────────
@app.get('/api/gc')
def get_gc():
    race_param = request.args.get('race', '')
    stage = request.args.get('stage', 'latest')
    fc_id, year = get_fc_info(race_param)

    try:
        race = RaceEdition(race_id=fc_id, year=year)
        # Se stage for numérico, a API filtra, senão traz o mais recente
        st_num = int(stage) if stage.isdigit() else None
        
        # Obter classificação geral (classification=1 no wrapper costuma ser GC)
        results = race.results(stage=st_num, classification=1)
        top20 = results.results_table.head(20).to_dict(orient='records')

        return jsonify({'race': race_param, 'stage': stage, 'top20': top20})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=False)
