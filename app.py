"""Painel local e receptor isolado de webhooks Datafy. Python 3.11+."""
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, timezone
from contextlib import contextmanager
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from waitress import serve

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # Local mode does not require PostgreSQL.
    psycopg = None

ROOT = Path(__file__).resolve().parent
LABELS = {'pendente': 'Sem resposta', 'aceitou': 'Aceitou', 'recusou': 'Recusou', 'revisar': 'A classificar', 'outra': 'Outra resposta'}
MANUAL = 'Revisão manual local'
DISCARDED = 'Descartado'

# Respostas curtas reconhecidas sem regra cadastrada (primeira palavra ou frase inteira).
POSITIVE = {'sim', 's', 'ss', 'quero', 'aceito', 'aceitar', 'autorizo', 'autorizar', 'confirmo', 'confirmar',
            'confirmado', 'confirmada', 'ok', 'okay', 'pode', 'claro', 'positivo', 'yes', 'bora', 'concordo',
            'tenho interesse', 'com certeza', 'de acordo', 'quero sim', 'pode sim', 'pode enviar', 'pode mandar', '👍'}
NEGATIVE = {'nao', 'n', 'recuso', 'recusar', 'cancelar', 'cancela', 'sair', 'parar', 'pare', 'stop', 'negativo',
            'no', 'remover', 'descadastrar', 'bloquear', 'nao quero', 'nao tenho interesse', 'sem interesse', 'nao autorizo', '👎'}

# Palavras que só valem como resposta inteira ("Ok"), não como começo de frase ("Pode me explicar...").
WEAK = {'ok', 'okay', 'pode', 'bora', 'no', 'n', 's'}
# "Não sei", "não entendi"... são dúvidas, não recusas.
UNSURE = {'sei', 'entendi', 'lembro', 'recebi', 'consigo', 'vi', 'conheco', 'entendo'}

def reply_intent(text):
    """'aceitou', 'recusou' ou '' para respostas curtas como "Sim, autorizo" ou "Não"."""
    emoji = str(text).strip()
    if '?' in emoji:  # Pergunta não é resposta.
        return ''
    plain = unicodedata.normalize('NFKD', emoji).encode('ascii', 'ignore').decode().lower()
    plain = re.sub(r'[^a-z0-9 ]+', ' ', plain).split()
    if not plain:
        return 'aceitou' if emoji in POSITIVE else 'recusou' if emoji in NEGATIVE else ''
    if len(plain) > 6:  # Texto longo precisa de leitura humana.
        return ''
    whole, first = ' '.join(plain), plain[0]
    if first == 'nao' and len(plain) > 1 and plain[1] in UNSURE:
        return ''
    if whole in NEGATIVE or (first in NEGATIVE and first not in WEAK):
        return 'recusou'
    if whole in POSITIVE or (first in POSITIVE and first not in WEAK):
        return 'aceitou'
    return ''

# Códigos de erro mais comuns da Cloud API, em linguagem do dia a dia.
FAIL_REASONS = {
    131026: 'Número sem WhatsApp ou que não pode receber a mensagem',
    131047: 'Mais de 24h sem conversa com a pessoa: só template pode ser enviado',
    131049: 'A Meta segurou a mensagem para evitar excesso de marketing para essa pessoa',
    131050: 'A pessoa optou por não receber mensagens de marketing',
    131042: 'Problema de pagamento na conta da Meta',
    131048: 'Envio limitado pela Meta por excesso de bloqueios/denúncias',
    131056: 'Muitas mensagens para o mesmo número em pouco tempo',
    131051: 'Tipo de mensagem não suportado',
    131052: 'Não foi possível baixar a mídia da mensagem',
    131053: 'Não foi possível enviar a mídia da mensagem',
    132000: 'Template com número errado de variáveis',
    132001: 'Template não existe ou não foi aprovado nesse idioma',
    132005: 'Texto do template ficou grande demais',
    132007: 'Conteúdo do template viola as regras da Meta',
    132012: 'Variáveis do template no formato errado',
    132015: 'Template pausado pela Meta por baixa qualidade',
    132016: 'Template desativado pela Meta',
    130472: 'A Meta não entregou (número em experimento da Meta)',
    131000: 'Erro interno do WhatsApp; tente de novo',
    131021: 'Mensagem para o próprio número',
    131031: 'Conta do WhatsApp Business bloqueada',
    368: 'Conta temporariamente bloqueada por violar políticas',
    470: 'Mais de 24h sem conversa com a pessoa: só template pode ser enviado',
}

# O que a pessoa pode fazer em cada caso.
FAIL_TIPS = {
    131026: 'Confira se o número está certo e tem WhatsApp. Se estiver, o app da pessoa pode estar desatualizado.',
    131047: 'Envie usando um template aprovado.',
    470: 'Envie usando um template aprovado.',
    131049: 'Não reenvie agora: a Meta limita mensagens de marketing por pessoa. Tente outro dia.',
    131050: 'A pessoa pediu para não receber marketing. Tire o número das próximas listas.',
    131042: 'Confira a forma de pagamento no Gerenciador do WhatsApp da Meta.',
    131048: 'Diminua o volume de envios e revise o texto: muita gente bloqueou ou denunciou.',
    131056: 'Espere alguns minutos antes de enviar de novo para esse número.',
    132000: 'Confira as variáveis do template na Datafy.',
    132012: 'Confira as variáveis do template na Datafy.',
    132001: 'Confira o nome e o idioma do template na Datafy.',
    132015: 'Use outro template ou edite este para melhorar a qualidade.',
    132016: 'Use outro template.',
    130472: 'Nada a fazer: a Meta segurou a mensagem por um teste interno dela.',
    131000: 'Tente enviar de novo mais tarde.',
}

def fail_info(raw):
    """Motivo, sugestão e detalhe técnico de um status 'failed'."""
    try:
        err = (json.loads(raw).get('errors') or [{}])[0]
    except (ValueError, TypeError, AttributeError):
        err = {}
    code = err.get('code')
    detail = (err.get('error_data') or {}).get('details') or err.get('message') or err.get('title') or ''
    if not code and not detail:
        return {'reason': 'Motivo não informado', 'tip': 'A Datafy não mandou o motivo desta falha. Confira o envio no painel da Datafy.', 'tech': ''}
    return {'reason': FAIL_REASONS.get(code) or detail or 'Falha no envio',
            'tip': FAIL_TIPS.get(code, 'Confira o envio no painel da Datafy.'),
            'tech': ' · '.join(x for x in (f'Código {code}' if code else '', detail) if x)}

def fail_reason(raw):
    return fail_info(raw)['reason']

def campaign_clock():
    return int(time.time())

def normalized(value):
    return unicodedata.normalize('NFC', str(value)).strip().casefold()

def phone(value):
    result = re.sub(r'\D', '', str(value))
    if not 10 <= len(result) <= 15:
        raise ValueError('Telefone inválido. Use DDI + DDD + número, como 5511999999999.')
    return result

def phone_key(value):
    """Mesma chave para 5581999522801, 558199522801 e 81999522801.

    O WhatsApp informa celulares brasileiros sem o nono dígito (WA ID),
    enquanto as listas costumam trazê-lo.
    """
    digits = re.sub(r'\D', '', str(value))
    if len(digits) in (10, 11):
        digits = '55' + digits
    if digits.startswith('55') and len(digits) == 13 and digits[4] == '9':
        digits = digits[:4] + digits[5:]
    return digits

PHONE_HEADERS = {'telefone', 'phone', 'phone_number', 'numero', 'number', 'celular', 'whatsapp', 'wa_id', 'waid', 'fone', 'tel', 'mobile'}
NAME_HEADERS = {'nome', 'name', 'nome_completo', 'cliente', 'first_name', 'primeiro_nome', 'full_name',
                'responsavel', 'contato', 'nome_contato', 'nome_do_contato'}

def header_key(value):
    # "Número de WhatsApp" -> "numero_de_whatsapp"
    text = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().strip().lower()
    return re.sub(r'[^a-z0-9]+', '_', text).strip('_')

def pretty_phone(value):
    digits = re.sub(r'\D', '', str(value))
    if digits.startswith('55') and len(digits) in (12, 13):
        local = digits[4:]
        if len(local) == 8 and local[0] in '6789':  # WA ID: celular sem o nono dígito.
            local = '9' + local
        return f'+55 ({digits[2:4]}) {local[:-4]}-{local[-4:]}'
    return '+' + digits if digits else ''

def brasilia(value):
    try:
        tz = ZoneInfo('America/Sao_Paulo')
    except ZoneInfoNotFoundError:
        from datetime import timedelta
        tz = timezone(timedelta(hours=-3))
    return datetime.fromtimestamp(int(value), tz)

def date_text(value):
    if not value:
        return ''
    return brasilia(value).strftime('%d/%m/%Y %H:%M:%S')

def duration_text(seconds):
    if seconds is None:
        return ''
    minutes = round(seconds / 60)
    if minutes < 60:
        return f'{max(minutes, 1)} min'
    hours = seconds / 3600
    if hours < 24:
        return f'{hours:.1f} h'.replace('.0 h', ' h').replace('.', ',')
    return f'{hours / 24:.1f} dias'.replace('.0 dias', ' dias').replace('.', ',')

# Faixas de tempo entre o disparo e a leitura/resposta.
DELAY_BUCKETS = [(300, 'até 5 min'), (900, '5–15 min'), (3600, '15–60 min'), (3 * 3600, '1–3 h'),
                 (6 * 3600, '3–6 h'), (86400, '6–24 h'), (3 * 86400, '1–3 dias'), (float('inf'), '+3 dias')]
WEEKDAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']

def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

def create_apps(db_path=None, settings=None):
    if settings is None:
        cfg = ROOT / 'config.json'
        settings = json.loads(cfg.read_text(encoding='utf-8-sig')) if cfg.exists() else {}
    settings = dict(settings)
    settings['webhook_secret'] = os.environ.get('DATAFY_WEBHOOK_SECRET', settings.get('webhook_secret', '')).strip().strip('"\'')
    settings['phone_number_id'] = str(os.environ.get('DATAFY_PHONE_NUMBER_ID', settings.get('phone_number_id', ''))).strip()
    database_url = os.environ.get('DATABASE_URL', '') if db_path is None else ''
    if database_url.startswith('postgres://'):
        database_url = 'postgresql://' + database_url[len('postgres://'):]
    db_path = Path(db_path or ROOT / 'dados' / 'relatorios.sqlite3')
    if not database_url:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    class Database:
        def __init__(self, raw, postgres=False):
            self.raw, self.postgres = raw, postgres
        def execute(self, sql, params=()):
            if self.postgres:
                if sql.strip().upper() == 'BEGIN IMMEDIATE':
                    sql = 'BEGIN'
                sql = sql.replace('?', '%s')
            return self.raw.execute(sql, params)
        def executescript(self, script):
            if self.postgres:
                for statement in script.split(';'):
                    if statement.strip() and not statement.lstrip().upper().startswith('PRAGMA'):
                        self.raw.execute(statement)
            else:
                self.raw.executescript(script)

    @contextmanager
    def connect():
        if database_url:
            if psycopg is None:
                raise RuntimeError('Instale psycopg para usar PostgreSQL.')
            raw = psycopg.connect(database_url, row_factory=dict_row)
            db = Database(raw, True)
        else:
            raw = sqlite3.connect(db_path, timeout=20)
            raw.row_factory = sqlite3.Row
            raw.execute('PRAGMA foreign_keys=ON')
            db = Database(raw)
        try:
            with raw:
                yield db
        finally:
            raw.close()

    with connect() as db:
        schema = '''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS contacts (
          id INTEGER PRIMARY KEY, campaign TEXT NOT NULL, name TEXT NOT NULL,
          phone TEXT NOT NULL, outbound TEXT UNIQUE,
          UNIQUE(campaign,phone));
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, phone TEXT, channel TEXT,
          ts INTEGER NOT NULL, context TEXT, body TEXT, choice TEXT, result TEXT,
          contact_id INTEGER REFERENCES contacts(id), association TEXT, raw TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_contact ON events(contact_id,ts);
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, event_id TEXT, action TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaign_windows (
          id INTEGER PRIMARY KEY, campaign TEXT NOT NULL, started INTEGER NOT NULL, ended INTEGER);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_window ON campaign_windows((1)) WHERE ended IS NULL;
        CREATE TABLE IF NOT EXISTS outbounds (
          id TEXT PRIMARY KEY, contact_id INTEGER NOT NULL REFERENCES contacts(id));
        INSERT INTO outbounds SELECT outbound,id FROM contacts WHERE outbound IS NOT NULL ON CONFLICT DO NOTHING;
        CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        '''
        if database_url:
            schema = schema.replace('id INTEGER PRIMARY KEY', 'id BIGSERIAL PRIMARY KEY')
        db.executescript(schema)

    panel = Flask(__name__)
    panel.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    panel.config.update(MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')))
    webhook = Flask('datafy_webhook')
    webhook.config['MAX_CONTENT_LENGTH'] = 2*1024*1024

    @panel.before_request
    def csrf_check():
        # CSS, JS e logo são públicos: a própria tela de login depende deles.
        public = request.endpoint in ('login', 'health', 'static') or request.path == '/webhook/datafy'
        if not public and os.environ.get('PANEL_PASSWORD') and not session.get('authenticated'):
            return redirect(url_for('login', next=request.path))
        if request.method == 'POST' and not secrets.compare_digest(session.get('csrf', ''), request.form.get('csrf', '!')):
            if request.path != '/webhook/datafy':
                abort(403)
        session.setdefault('csrf', secrets.token_hex(24))

    @panel.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
        if os.environ.get('RENDER'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @panel.route('/login', methods=['GET','POST'])
    def login():
        if request.method == 'POST':
            username = os.environ.get('PANEL_USERNAME', 'admin')
            password = os.environ.get('PANEL_PASSWORD', '')
            # Usuário não diferencia maiúsculas ("Admin" = "admin"); a senha diferencia.
            typed = request.form.get('username','').strip().lower()
            ok = password and secrets.compare_digest(typed.encode(), username.strip().lower().encode())
            ok = ok and secrets.compare_digest(request.form.get('password',''), password)
            if ok:
                session.clear()
                session['authenticated'] = True
                session['csrf'] = secrets.token_hex(24)
                return redirect(url_for('index'))
            flash('Usuário ou senha inválidos.')
        return render_template('login.html')

    @panel.post('/sair')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @panel.get('/healthz')
    def health():
        return {'ok': True}, 200

    def classify(choice, body='', rules=None):
        # Regra cadastrada para o botão vence; senão, reconhece respostas curtas óbvias.
        val = normalized(choice)
        rules = rules or get_rules()
        yes = {normalized(v) for v in rules.get('aceite', [])}
        no = {normalized(v) for v in rules.get('recusa', [])}
        if val and val in yes and val not in no:
            return 'aceitou'
        if val and val in no and val not in yes:
            return 'recusou'
        return reply_intent(body) or reply_intent(choice) or 'revisar'

    def get_rules():
        rules = {k: settings.get(k, []) for k in ('aceite','recusa')}
        with connect() as db:
            for row in db.execute('SELECT * FROM preferences'):
                if row['key'] in rules:
                    rules[row['key']] = json.loads(row['value'])
        return rules

    def link_by_context(db):
        db.execute('''INSERT INTO outbounds SELECT outbound,id FROM contacts WHERE outbound IS NOT NULL ON CONFLICT DO NOTHING''')
        outs = {r['id']: r for r in db.execute('''SELECT o.id, o.contact_id, c.phone FROM outbounds o
            JOIN contacts c ON c.id=o.contact_id''').fetchall()}
        loose = db.execute('''SELECT id,kind,phone,ts,context FROM events WHERE contact_id IS NULL
            AND COALESCE(association,'')<>? ORDER BY ts''',(DISCARDED,)).fetchall()
        if not loose:
            return
        # Horário de cada envio conhecido, para ligar respostas escritas direto na conversa.
        sent_at = {}
        for r in db.execute("SELECT context, MIN(ts) AS ts FROM events WHERE kind='status' AND context IS NOT NULL GROUP BY context").fetchall():
            if r['context'] in outs:
                sent_at[r['context']] = r['ts']
        by_phone = {}
        for context, ts in sent_at.items():
            by_phone.setdefault(phone_key(outs[context]['phone']), []).append((ts, outs[context]['contact_id']))
        for ev in loose:
            out = outs.get(ev['context'])
            if out and (ev['kind']=='status' or phone_key(out['phone'])==phone_key(ev['phone'])):
                db.execute('UPDATE events SET contact_id=?,association=? WHERE id=?',(out['contact_id'],'ID da mensagem enviada',ev['id']))
            elif ev['kind']=='reply':
                # Sem "responder" na mensagem: vale o envio mais recente para esse número antes da resposta.
                earlier = [s for s in by_phone.get(phone_key(ev['phone']), []) if s[0] <= ev['ts']]
                if earlier:
                    db.execute('UPDATE events SET contact_id=?,association=? WHERE id=?',(max(earlier)[1],'Envio mais recente para o número',ev['id']))

    def reclassify(db, rules=None):
        # Aplica regras novas e o reconhecimento automático às respostas ainda sem classificação.
        # Quem acabou de gravar regras nesta transação passa as regras (outra conexão ainda não as vê).
        rules = rules or get_rules()
        for ev in db.execute("""SELECT id,choice,body FROM events WHERE kind='reply' AND result='revisar'
                AND COALESCE(association,'') NOT IN (?,?)""",(MANUAL,DISCARDED)).fetchall():
            result = classify(ev['choice'], ev['body'], rules)
            if result != 'revisar':
                db.execute('UPDATE events SET result=? WHERE id=?',(result,ev['id']))

    def attach(db, contact_id, context):
        db.execute('INSERT INTO outbounds VALUES(?,?) ON CONFLICT DO NOTHING',(context,contact_id))
        db.execute('UPDATE contacts SET outbound=COALESCE(outbound,?) WHERE id=?',(context,contact_id))

    def capture_sends(db):
        # A Datafy não informa a campanha no webhook. O envio ('sent', ou 'failed' quando
        # nem chegou a sair) é ligado pelo telefone ao contato de uma lista importada que
        # ainda não tem envio: o envio mais recente fica com a lista mais recente, então
        # várias campanhas podem rodar ao mesmo tempo.
        # Sem lista, vale a captura por horário (modo antigo), se estiver ligada.
        # Entrega/leitura podem chegar dias depois e nunca escolhem campanha.
        waiting = {}
        for c in db.execute('SELECT id,phone FROM contacts WHERE outbound IS NULL ORDER BY id DESC').fetchall():
            waiting.setdefault(phone_key(c['phone']), []).append(c['id'])
        for ev in db.execute("""SELECT * FROM events WHERE kind='status' AND body IN ('sent','failed')
                AND contact_id IS NULL ORDER BY ts DESC""").fetchall():
            if not ev['context'] or not 10 <= len(ev['phone'] or '') <= 15:
                continue
            if db.execute('SELECT 1 FROM outbounds WHERE id=?',(ev['context'],)).fetchone():
                continue
            listed = waiting.get(phone_key(ev['phone']))
            if listed:
                attach(db, listed.pop(0), ev['context'])
                continue
            window = db.execute('''SELECT campaign FROM campaign_windows WHERE started<=?
                AND (ended IS NULL OR ?<ended) ORDER BY started DESC LIMIT 1''',(ev['ts'],ev['ts'])).fetchone()
            if not window:
                continue
            db.execute('''INSERT INTO contacts(campaign,name,phone)
              VALUES(?,?,?) ON CONFLICT(campaign,phone) DO NOTHING''',(window['campaign'],ev['phone'],ev['phone']))
            contact = db.execute('SELECT id FROM contacts WHERE campaign=? AND phone=?',(window['campaign'],ev['phone'])).fetchone()
            attach(db, contact['id'], ev['context'])

    @webhook.post('/webhook/datafy')
    def receive():
        secret = settings.get('webhook_secret', '')
        channel = str(settings.get('phone_number_id', '')).strip()
        if not secret or not channel:
            return {'error': 'Configure secret e phone_number_id no servidor'}, 503
        raw = request.get_data()
        stamp = request.headers.get('x-datafy-timestamp', '')
        sig = request.headers.get('x-datafy-signature-256', '')
        try:
            if abs(time.time() - int(stamp)) > 300:
                print(f'[webhook 401] timestamp fora da janela: {stamp!r} (agora {int(time.time())})', flush=True)
                abort(401)
        except ValueError:
            print(f'[webhook 401] timestamp ausente/inválido: {stamp!r}', flush=True)
            abort(401)
        expected = 'sha256=' + hmac.new(secret.encode(), stamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected.encode(), sig.encode()):
            print(f'[webhook 401] assinatura não confere: recebida={sig[:16]!r}... '
                  f'secret_prefixo={secret[:9]!r} secret_len={len(secret)} corpo={len(raw)} bytes', flush=True)
            abort(401)
        try:
            payload = json.loads(raw)
            records = []
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    if change.get('field') != 'messages':
                        continue
                    number = str(value.get('metadata', {}).get('phone_number_id', ''))
                    if number != channel:
                        continue
                    for msg in value.get('messages', []):
                        kind = msg.get('type', '')
                        choice = ''
                        body = ''
                        if kind == 'text':
                            body = msg.get('text', {}).get('body', '')
                        elif kind == 'button':
                            button = msg.get('button', {})
                            body = button.get('text', '')
                            choice = button.get('payload') or body
                        elif kind == 'interactive':
                            inter = msg.get('interactive', {})
                            button = inter.get(inter.get('type', ''), {})
                            body = button.get('title', '')
                            choice = button.get('id') or body
                        else:
                            body = '[Mensagem de tipo: '+kind+']'
                        result = classify(choice, body) if kind in ('text','button','interactive') else 'revisar'
                        context = msg.get('context', {}).get('id')
                        records.append((number+':message:'+msg['id'], 'reply', phone(msg['from']), number,
                            int(msg['timestamp']), context, str(body), str(choice), result, json.dumps(msg, ensure_ascii=False)))
                    for status in value.get('statuses', []):
                        state = status.get('status', '')
                        if state not in ('sent', 'delivered', 'read', 'failed'):
                            continue
                        records.append((number+':status:'+status['id']+':'+state, 'status',
                            re.sub(r'\D', '', str(status.get('recipient_id', ''))), number,
                            int(status['timestamp']), status['id'], state, '', '', json.dumps(status, ensure_ascii=False)))
            with connect() as db:
                for rec in records:
                    db.execute('''INSERT INTO events
                      (id,kind,phone,channel,ts,context,body,choice,result,raw) VALUES (?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(id) DO NOTHING''', rec)
                capture_sends(db)
                link_by_context(db)
            return {'ok': True}, 200
        except (ValueError, KeyError, TypeError, AttributeError):
            return {'error': 'Formato de evento inválido'}, 400

    def report(campaign=''):
        with connect() as db:
            contacts = db.execute("SELECT * FROM contacts WHERE (?='' OR campaign=?) ORDER BY campaign,name,phone", (campaign,campaign)).fetchall()
            events = db.execute('SELECT * FROM events WHERE contact_id IS NOT NULL ORDER BY ts,id').fetchall()
        by_contact = {}
        for ev in events:
            by_contact.setdefault(ev['contact_id'], []).append(dict(ev))
        rows = []
        for item in contacts:
            row = dict(item)
            evs = by_contact.get(row['id'], [])
            replies = [e for e in evs if e['kind']=='reply']
            statuses = {e['body'] for e in evs if e['kind']=='status'}
            row['status'], row['delivery'] = next(((code,label) for code,label in [('read','Lida'),('delivered','Entregue'),('failed','Falhou'),('sent','Enviada')] if code in statuses), ('none','Não informado'))
            status_ts = [e['ts'] for e in evs if e['kind']=='status' and e['body']==row['status']]
            row['status_when'] = date_text(status_ts[-1]) if status_ts else ''
            row['replied'] = bool(replies)
            row['last_ts'] = max((e['ts'] for e in evs), default=0)
            row['phone_fmt'] = pretty_phone(row['phone'])
            row['name_fmt'] = '' if row['name']==row['phone'] else row['name']
            failed = [e for e in evs if e['kind']=='status' and e['body']=='failed']
            row['fail'] = fail_info(failed[-1]['raw']) if failed and row['status']=='failed' else None
            row['fail_reason'] = row['fail']['reason'] if row['fail'] else ''
            row['result'] = replies[-1]['result'] if replies else 'pendente'
            row['answer'] = replies[-1]['body'] if replies else ''
            row['choice'] = replies[-1]['choice'] if replies else ''
            row['when'] = date_text(replies[-1]['ts']) if replies else ''
            row['association'] = replies[-1]['association'] if replies else ''
            rows.append(row)
        totals = {k: sum(r['result']==k for r in rows) for k in LABELS}
        totals.update(total=len(rows), delivered=sum(r['delivery'] in ('Entregue','Lida') for r in rows), read=sum(r['delivery']=='Lida' for r in rows),
            sent=sum(r['status']!='none' for r in rows), failed=sum(r['status']=='failed' for r in rows), replied=sum(r['replied'] for r in rows))
        totals['reasons'] = sorted(((n, reason) for reason, n in
            {r['fail_reason']: sum(x['fail_reason']==r['fail_reason'] for x in rows) for r in rows if r['fail_reason']}.items()), reverse=True)
        return rows, totals

    def analytics(days, campaign=''):
        """Dados dos gráficos: envios feitos no período (e na campanha, se escolhida)."""
        cutoff = time.time() - days * 86400 if days else 0
        with connect() as db:
            owner = {r['id']: r['campaign'] for r in db.execute('SELECT id,campaign FROM contacts').fetchall()}
            events = db.execute('''SELECT kind,body,ts,contact_id,result FROM events
                WHERE contact_id IS NOT NULL ORDER BY ts''').fetchall()
            failures = db.execute("""SELECT context,raw,ts,contact_id FROM events WHERE kind='status' AND body='failed'
                AND COALESCE(association,'')<>? ORDER BY ts""",(DISCARDED,)).fetchall()
        people = {}
        for e in events:
            p = people.setdefault(e['contact_id'], {'send': None, 'delivered': False, 'read': None, 'replies': []})
            if e['kind'] == 'status':
                p['send'] = e['ts'] if p['send'] is None else min(p['send'], e['ts'])
                if e['body'] in ('delivered', 'read'):
                    p['delivered'] = True
                if e['body'] == 'read' and p['read'] is None:
                    p['read'] = e['ts']
            else:
                p['replies'].append(e)
        chosen = {cid: p for cid, p in people.items()
                  if p['send'] and p['send'] >= cutoff and (not campaign or owner.get(cid) == campaign)}

        # 1. Comparativo entre campanhas (ignora o filtro de campanha, respeita o período).
        per = {}
        for cid, p in people.items():
            if not p['send'] or p['send'] < cutoff:
                continue
            c = per.setdefault(owner[cid], {'name': owner[cid], 'sent': 0, 'delivered': 0, 'read': 0,
                                            'replied': 0, 'accepted': 0, 'last': 0})
            c['sent'] += 1
            c['delivered'] += p['delivered']
            c['read'] += bool(p['read'])
            c['replied'] += bool(p['replies'])
            c['accepted'] += bool(p['replies']) and p['replies'][-1]['result'] == 'aceitou'
            c['last'] = max(c['last'], p['send'])
        compare = sorted(per.values(), key=lambda c: c['last'], reverse=True)[:8]
        for c in compare:
            for k in ('delivered', 'read', 'replied', 'accepted'):
                c[k + '_pct'] = round(c[k] * 100 / c['sent'], 1) if c['sent'] else 0

        # 2. Tempo entre o disparo e a leitura/resposta.
        read_delays = [p['read'] - p['send'] for p in chosen.values() if p['read'] and p['read'] >= p['send']]
        reply_delays = []
        for p in chosen.values():
            after = [r['ts'] for r in p['replies'] if r['ts'] >= p['send']]
            if after:
                reply_delays.append(min(after) - p['send'])
        def bucket(values):
            counts = [0] * len(DELAY_BUCKETS)
            for v in values:
                counts[next(i for i, (edge, _) in enumerate(DELAY_BUCKETS) if v < edge)] += 1
            return [round(n * 100 / len(values), 1) if values else 0 for n in counts], counts
        read_pct, read_n = bucket(read_delays)
        reply_pct, reply_n = bucket(reply_delays)

        # 3. Dia da semana × hora das respostas (horário de Brasília).
        heat = [[0] * 24 for _ in WEEKDAYS]
        replies_total = 0
        for p in chosen.values():
            for r in p['replies']:
                local = brasilia(r['ts'])
                heat[local.weekday()][local.hour] += 1
                replies_total += 1
        peak = max(((heat[d][h], d, h) for d in range(7) for h in range(24)), default=(0, 0, 0))

        # 4. Motivos das falhas (inclui envios sem campanha quando não há filtro de campanha).
        reasons, seen = {}, set()
        for f in failures:
            if f['ts'] < cutoff or f['context'] in seen:
                continue
            if campaign and owner.get(f['contact_id']) != campaign:
                continue
            seen.add(f['context'])
            reason = fail_reason(f['raw'])
            reasons[reason] = reasons.get(reason, 0) + 1
        ranked = sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) > 7:
            ranked = ranked[:6] + [('Outros motivos', sum(n for _, n in ranked[6:]))]

        best = max((c for c in compare if c['sent'] >= 1), key=lambda c: c['replied_pct'], default=None)
        return {
            'sent': len(chosen), 'replies': replies_total,
            'compare': compare, 'show_accepted': any(c['accepted'] for c in compare),
            'best': best if len(compare) > 1 else None,
            'buckets': [label for _, label in DELAY_BUCKETS],
            'read_pct': read_pct, 'read_n': read_n, 'reply_pct': reply_pct, 'reply_n': reply_n,
            'reads': len(read_delays), 'answered': len(reply_delays),
            'median_read': duration_text(median(read_delays)), 'median_reply': duration_text(median(reply_delays)),
            'weekdays': WEEKDAYS, 'heat': heat, 'peak': {'n': peak[0], 'day': WEEKDAYS[peak[1]], 'hour': peak[2]},
            'failures': [{'reason': r, 'n': n} for r, n in ranked], 'failed': sum(reasons.values()),
        }

    @panel.get('/')
    def index():
        tab = request.args.get('aba') if request.args.get('aba') in ('config', 'graficos') else 'painel'
        all_rows = report()[0]
        with connect() as db:
            active = db.execute('SELECT * FROM campaign_windows WHERE ended IS NULL').fetchone()
            campaigns = [r['campaign'] for r in db.execute('SELECT campaign FROM contacts UNION SELECT campaign FROM campaign_windows ORDER BY campaign')]
            loose = db.execute("""SELECT context,phone,ts,body,raw FROM events WHERE kind='status'
                AND contact_id IS NULL AND context IS NOT NULL AND COALESCE(association,'')<>? ORDER BY ts""",(DISCARDED,)).fetchall()
            # Respostas ligadas a um contato que o reconhecimento automático não entendeu.
            inbox = db.execute("""SELECT e.*, c.campaign, c.name FROM events e JOIN contacts c ON c.id=e.contact_id
                WHERE e.kind='reply' AND e.result='revisar' ORDER BY e.ts DESC LIMIT 200""").fetchall()
            # Mensagens de quem não recebeu nenhum disparo registrado.
            outside = db.execute("""SELECT * FROM events WHERE kind='reply' AND contact_id IS NULL
                AND COALESCE(association,'')<>? ORDER BY ts DESC LIMIT 200""",(DISCARDED,)).fetchall()
            last = db.execute('SELECT MAX(ts) AS last_ts FROM events').fetchone()['last_ts']
        # Abre na campanha com atividade mais recente; "Todas" é uma escolha explícita (vazia).
        recent = max(all_rows, key=lambda r: r['last_ts'], default=None)
        default = active['campaign'] if active else (recent['campaign'] if recent and recent['last_ts'] else '')
        campaign = request.args.get('campanha', default)
        rows, totals = report(campaign)
        rows.sort(key=lambda r: r['last_ts'], reverse=True)  # Atividade mais recente primeiro.
        # Envios sem campanha agrupados por número, com o status mais avançado do último envio.
        order = {'sent': 1, 'delivered': 2, 'read': 3, 'failed': 4}
        sends = {}
        for ev in loose:
            s = sends.setdefault(ev['context'], {'context': ev['context'], 'phone': ev['phone'], 'first': ev['ts'], 'status': ev['body'], 'raw': ev['raw']})
            if order.get(ev['body'], 0) > order.get(s['status'], 0):
                s['status'], s['raw'] = ev['body'], ev['raw']
        groups = {}
        for s in sorted(sends.values(), key=lambda s: s['first']):
            g = groups.setdefault(phone_key(s['phone']), {'phone': s['phone'], 'contexts': [], 'first': s['first']})
            g['contexts'].append(s['context'])
            g.update(last=s['first'], status=s['status'], fail=fail_info(s['raw']) if s['status']=='failed' else None)
        unlinked_sends = sorted(groups.values(), key=lambda g: g['last'], reverse=True)[:500]
        rules = get_rules()
        show_results = bool(totals['aceitou'] or totals['recusou'] or rules.get('aceite') or rules.get('recusa'))
        period = request.args.get('periodo', '30')
        period = period if period in ('7', '30', '90', 'tudo') else '30'
        charts = None
        if tab == 'graficos':
            # Nos gráficos, "Todas" é o padrão: o comparativo já mostra cada campanha.
            campaign = request.args.get('campanha', '')
            charts = analytics(0 if period == 'tudo' else int(period), campaign)
        return render_template('index.html', rows=rows, totals=totals, campaigns=campaigns,
            charts=charts, period=period,
            campaign=campaign, inbox=inbox, outside=outside, labels=LABELS, date_text=date_text,
            configured=bool(settings.get('webhook_secret') and settings.get('phone_number_id')),
            last=date_text(last), rules=rules, active=active, show_results=show_results,
            unlinked=len(sends), unlinked_sends=unlinked_sends, hosted=bool(os.environ.get('PANEL_PASSWORD')),
            tab=tab, pretty_phone=pretty_phone)

    @panel.post('/campanha')
    def campaign_control():
        action = request.form.get('acao')
        name = request.form.get('nome','').strip()
        if action not in ('ativar','encerrar') or (action=='ativar' and not 1 <= len(name) <= 150):
            abort(400)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute('SELECT * FROM campaign_windows WHERE ended IS NULL').fetchone()
            if action=='ativar' and active:
                flash('Encerre a campanha ativa antes de iniciar outra.')
            else:
                now = campaign_clock()
                if active:
                    db.execute('UPDATE campaign_windows SET ended=? WHERE id=?',(now,active['id']))
                if action=='ativar':
                    db.execute('INSERT INTO campaign_windows(campaign,started) VALUES(?,?)',(name,now))
                db.execute('INSERT INTO audit(ts,action) VALUES(?,?)',(now,json.dumps({'campaign':name,'action':action})))
                flash('Campanha ativada. Inicie os disparos na Datafy.' if action=='ativar' else 'Captação de novos envios encerrada. Atualizações dos envios registrados continuam chegando.')
        return redirect(url_for('index'))

    @panel.post('/regras')
    def save_rules():
        rules = {k:[v.strip() for v in request.form.get(k,'').splitlines() if v.strip()] for k in ('aceite','recusa')}
        if {normalized(v) for v in rules['aceite']} & {normalized(v) for v in rules['recusa']}:
            flash('Uma opção não pode representar aceite e recusa ao mesmo tempo.')
            return redirect(url_for('index', aba='config'))
        with connect() as db:
            for k,v in rules.items():
                db.execute('''INSERT INTO preferences(key,value) VALUES(?,?)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value''',(k,json.dumps(v)))
            reclassify(db, rules)
        flash('Regras salvas. Respostas ainda sem classificação foram atualizadas.')
        return redirect(url_for('index', aba='config'))

    @panel.post('/importar')
    def import_csv():
        try:
            upload = request.files.get('arquivo')
            if not upload:
                raise ValueError('Selecione um CSV.')
            data = upload.read()
            try:
                raw = data.decode('utf-8-sig')
            except UnicodeDecodeError:  # CSV salvo pelo Excel no Windows.
                raw = data.decode('cp1252')
            try:
                dialect = csv.Sniffer().sniff(raw[:4096], delimiters=';,\t')
            except csv.Error:
                dialect = csv.excel
            table = [r for r in csv.reader(io.StringIO(raw), dialect=dialect) if any(c.strip() for c in r)]
            if not table:
                raise ValueError('O arquivo está vazio.')
            looks_phone = lambda v: bool(re.fullmatch(r'[\d\s()+.-]+', v.strip())) and 10 <= len(re.sub(r'\D','',v)) <= 15
            keys = [header_key(h) for h in table[0]]
            has_header = not any(looks_phone(c) for c in table[0])
            body = table[1:] if has_header else table
            width = max(len(r) for r in body) if body else 0
            col = lambda r, i: r[i].strip() if i is not None and i < len(r) else ''
            # Coluna de telefone: pelo cabeçalho ou pela que mais parece telefone.
            phone_col = next((i for i,k in enumerate(keys) if has_header and k in PHONE_HEADERS), None)
            if phone_col is None:
                scores = [sum(looks_phone(col(r,i)) for r in body) for i in range(width)]
                if scores and max(scores) * 2 >= len(body) and max(scores) > 0:
                    phone_col = scores.index(max(scores))
            if phone_col is None:
                raise ValueError('Não encontrei a coluna de telefone. Use um cabeçalho como "telefone".')
            name_col = next((i for i,k in enumerate(keys) if has_header and i != phone_col and (k in NAME_HEADERS or k.startswith('nome'))), None)
            if name_col is None and not has_header:
                name_col = next((i for i in range(width) if i != phone_col and
                    sum(bool(col(r,i)) and not looks_phone(col(r,i)) for r in body) * 2 >= len(body)), None)
            campaign_col = keys.index('campanha') if has_header and 'campanha' in keys else None
            outbound_col = keys.index('mensagem_id') if has_header and 'mensagem_id' in keys else None
            chosen = request.form.get('campanha', '').strip()
            if not chosen and campaign_col is None:
                raise ValueError('Informe o nome da campanha.')
            parsed, skipped = [], 0
            for n,row in enumerate(body, 2 if has_header else 1):
                campaign = chosen or col(row, campaign_col)
                try:
                    number = phone(col(row, phone_col))
                except ValueError:
                    skipped += 1
                    continue
                if len(number) in (10, 11):
                    number = '55' + number
                name = col(row, name_col) or number
                outbound = col(row, outbound_col) or None
                if not campaign or len(campaign)>150 or len(name)>200:
                    raise ValueError(f'Linha {n}: campanha precisa estar preenchida e ter até 150 caracteres; nome até 200.')
                if outbound and not outbound.startswith('wamid.'):
                    raise ValueError(f'Linha {n}: mensagem_id deve ser o wamid retornado no envio; deixe vazio se não tiver.')
                parsed.append((campaign,name,number,outbound))
            if not parsed:
                raise ValueError('O arquivo não contém telefones válidos.')
            with connect() as db:
                for campaign,name,number,outbound in parsed:
                    old = db.execute('SELECT outbound FROM contacts WHERE campaign=? AND phone=?',(campaign,number)).fetchone()
                    if old and old['outbound'] and outbound and old['outbound']!=outbound:
                        raise ValueError('Este contato já tem outro envio nesta campanha. Crie uma campanha diferente para novo disparo.')
                    db.execute('''INSERT INTO contacts(campaign,name,phone,outbound) VALUES(?,?,?,?)
                      ON CONFLICT(campaign,phone) DO UPDATE SET name=excluded.name,
                      outbound=COALESCE(contacts.outbound,excluded.outbound)''',(campaign,name,number,outbound))
                capture_sends(db)
                link_by_context(db)
                reclassify(db)
                names = sorted({p[0] for p in parsed})
                linked = sum(db.execute('SELECT COUNT(*) AS n FROM contacts WHERE campaign=? AND outbound IS NOT NULL',(c,)).fetchone()['n'] for c in names)
            msg = f'{len(parsed)} contato(s) importado(s) em “{", ".join(names)}”.'
            if linked:
                msg += f' {linked} já com envio registrado.'
            if skipped:
                msg += f' {skipped} linha(s) ignorada(s) por telefone inválido.'
            flash(msg)
        except (ValueError, UnicodeError, csv.Error, sqlite3.IntegrityError,
                psycopg.IntegrityError if psycopg else sqlite3.IntegrityError) as exc:
            flash('Importação cancelada: '+str(exc))
        return redirect(url_for('index', aba='config'))

    @panel.post('/mover')
    def move_unlinked():
        # Cada caixa marcada pode representar vários envios do mesmo número.
        contexts = [c for v in request.form.getlist('envio') for c in v.split()]
        if request.form.get('acao') == 'descartar':
            with connect() as db:
                for context in contexts:
                    db.execute("UPDATE events SET association=? WHERE kind='status' AND context=? AND contact_id IS NULL",(DISCARDED,context))
                db.execute('INSERT INTO audit(ts,action) VALUES(?,?)',(int(time.time()),json.dumps({'action':'descartar','envios':contexts})))
            flash(f'{len(contexts)} envio(s) descartado(s). Eles continuam no Excel de todas as campanhas.')
            return redirect(url_for('index', aba='config', _anchor='sem-campanha'))
        campaign = (request.form.get('nova','').strip() or request.form.get('campanha','').strip())
        if not 1 <= len(campaign) <= 150 or not contexts:
            flash('Marque pelo menos um envio e escolha a campanha.')
            return redirect(url_for('index', aba='config', _anchor='sem-campanha'))
        moved = 0
        with connect() as db:
            for context in contexts:
                ev = db.execute("""SELECT phone FROM events WHERE kind='status' AND context=?
                    AND contact_id IS NULL LIMIT 1""",(context,)).fetchone()
                if not ev or db.execute('SELECT 1 FROM outbounds WHERE id=?',(context,)).fetchone():
                    continue
                key = phone_key(ev['phone'])
                contact_id = next((c['id'] for c in db.execute('SELECT id,phone FROM contacts WHERE campaign=?',(campaign,)).fetchall()
                    if phone_key(c['phone'])==key), None)
                if contact_id is None:
                    db.execute('INSERT INTO contacts(campaign,name,phone) VALUES(?,?,?)',(campaign,ev['phone'],ev['phone']))
                    contact_id = db.execute('SELECT id FROM contacts WHERE campaign=? AND phone=?',(campaign,ev['phone'])).fetchone()['id']
                attach(db, contact_id, context)
                moved += 1
            link_by_context(db)
            reclassify(db)
            db.execute('INSERT INTO audit(ts,action) VALUES(?,?)',(int(time.time()),json.dumps({'action':'mover','campaign':campaign,'envios':contexts})))
        flash(f'{moved} envio(s) movido(s) para “{campaign}”.')
        return redirect(url_for('index', campanha=campaign))

    @panel.post('/revisar')
    def review():
        event_id = request.form.get('evento','')
        result = request.form.get('resultado','')
        if result not in ('aceitou','recusou','revisar','outra','descartar'):
            abort(400)
        with connect() as db:
            ev = db.execute("SELECT * FROM events WHERE id=? AND kind='reply'",(event_id,)).fetchone()
            if not ev:
                abort(400)
            if result == 'descartar':
                db.execute('UPDATE events SET association=? WHERE id=? AND contact_id IS NULL',(DISCARDED,event_id))
                db.execute('INSERT INTO audit(ts,event_id,action) VALUES(?,?,?)',(int(time.time()),event_id,json.dumps({'action':'descartar'})))
                flash('Mensagem descartada.')
                return redirect(url_for('index', aba='config'))
            # Sem contato informado, mantém o contato já ligado automaticamente.
            contact = db.execute('SELECT * FROM contacts WHERE id=?',(request.form.get('contato') or ev['contact_id'],)).fetchone()
            if not contact or phone_key(ev['phone']) != phone_key(contact['phone']):
                abort(400)
            db.execute('UPDATE events SET contact_id=?,result=?,association=? WHERE id=?', (contact['id'], result, MANUAL, event_id))
            db.execute('INSERT INTO audit(ts,event_id,action) VALUES(?,?,?)',(int(time.time()),event_id,json.dumps({'before_contact':ev['contact_id'],'before_result':ev['result'],'contact':contact['id'],'result':result})))
            # "Sempre contar este botão assim": vira regra e vale para as outras respostas iguais.
            if request.form.get('sempre') and ev['choice'] and result in ('aceitou','recusou'):
                rules = get_rules()
                key, other = ('aceite','recusa') if result=='aceitou' else ('recusa','aceite')
                rules[other] = [v for v in rules.get(other, []) if normalized(v) != normalized(ev['choice'])]
                if normalized(ev['choice']) not in {normalized(v) for v in rules.get(key, [])}:
                    rules[key] = rules.get(key, []) + [ev['choice']]
                for k in ('aceite','recusa'):
                    db.execute('''INSERT INTO preferences(key,value) VALUES(?,?)
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value''',(k,json.dumps(rules[k])))
                reclassify(db, rules)
                flash(f'Pronto. O botão “{ev["body"] or ev["choice"]}” agora sempre conta como {LABELS[result]}.')
            else:
                flash(f'Resposta marcada como {LABELS[result]}.')
        return redirect(url_for('index', aba='config'))

    @panel.get('/modelo.csv')
    def model():
        return send_file(io.BytesIO('campanha;nome;telefone\n'.encode('utf-8-sig')), as_attachment=True, download_name='modelo-contatos.csv', mimetype='text/csv')

    @panel.get('/relatorio.xlsx')
    def export():
        def append(ws, values):
            ws.append([re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', v) if isinstance(v,str) else v for v in values])
        campaign = request.args.get('campanha','')
        rows, totals = report(campaign)
        wb = Workbook()
        summary = wb.active
        summary.title = 'Resumo'
        for row in [['Disparos Construir — Relatório de campanha'],['Campanha',campaign or 'Todas'],['Gerado em', date_text(time.time())],['Indicador','Quantidade','Percentual da base'],['Contatos na base',totals['total'],1 if totals['total'] else 0],['Entregues (inclui lidas)',totals['delivered'],totals['delivered']/totals['total'] if totals['total'] else 0],['Leituras informadas',totals['read'],totals['read']/totals['total'] if totals['total'] else 0]]:
            summary.append(row)
        for k,label in LABELS.items():
            summary.append([label,totals[k],totals[k]/totals['total'] if totals['total'] else 0])
        summary.append(['Base importada não comprova envio. Sem status significa não informado.'])
        summary.append(['Respostas sem vínculo não entram nos resultados por campanha.'])
        summary.append(['Resultado considera a resposta vinculada mais recente, inclusive revisão.'])
        for r in range(5,8+len(LABELS)):
            summary.cell(r,3).number_format = '0.0%'
        detail = wb.create_sheet('Contatos')
        detail.append(['Campanha','Nome','Telefone','ID do envio','Entrega','Resultado','Resposta original','Opção (ID)','Data da resposta','Vínculo','Motivo da falha'])
        for row in rows:
            append(detail,[row['campaign'],row['name'],row['phone'],row['outbound'],row['delivery'],LABELS[row['result']],row['answer'],row['choice'],row['when'],row['association'],row['fail_reason']])
        history = wb.create_sheet('Histórico')
        history.append(['Campanha','Telefone','Tipo','Data','Conteúdo','Opção','Resultado','Vínculo','ID do evento'])
        with connect() as db:
            evs = db.execute('''SELECT e.*,c.campaign FROM events e LEFT JOIN contacts c ON c.id=e.contact_id
              WHERE (?='' OR c.campaign=?) ORDER BY e.ts''',(campaign,campaign)).fetchall()
        for ev in evs:
            append(history,[ev['campaign'] or 'Sem vínculo',ev['phone'],ev['kind'],date_text(ev['ts']),ev['body'],ev['choice'],LABELS.get(ev['result'],''),ev['association'],ev['id']])
        for ws in wb:
            ws.freeze_panes = 'A2'
            if ws != summary:
                ws.auto_filter.ref = ws.dimensions
            for cell in ws[1]:
                cell.fill = PatternFill('solid', fgColor='164E63')
                cell.font = Font(color='FFFFFF',bold=True)
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(55,max(16,max(len(str(c.value or '')) for c in col)+2))
            # Untrusted text must never become an Excel formula or illegal XML.
            for row in ws:
                for cell in row:
                    if isinstance(cell.value,str):
                        cell.value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cell.value)
                        cell.data_type = 's'
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name='relatorio-datafy.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @panel.get('/backup')
    def backup():
        if database_url:
            tables = ('contacts','events','audit','campaign_windows','outbounds','preferences')
            snapshot = {'generated_at': int(time.time()), 'tables': {}}
            with connect() as source:
                for table in tables:
                    snapshot['tables'][table] = [dict(row) for row in source.execute(f'SELECT * FROM {table}')]
            content = json.dumps(snapshot, ensure_ascii=False, indent=2).encode('utf-8')
            return send_file(io.BytesIO(content), as_attachment=True,
                download_name='backup-datafy.json', mimetype='application/json')
        # SQLite backup API includes committed WAL transactions.
        dest = sqlite3.connect(':memory:')
        try:
            with connect() as source:
                source.raw.backup(dest)
            content = dest.serialize()
        finally:
            dest.close()
        return send_file(io.BytesIO(content), as_attachment=True, download_name='backup-datafy.sqlite3', mimetype='application/octet-stream')

    # Liga e classifica eventos gravados antes de uma mudança nas regras de captura.
    with connect() as db:
        capture_sends(db)
        link_by_context(db)
        reclassify(db)

    return panel, webhook

def create_render_app(db_path=None, settings=None):
    panel, webhook = create_apps(db_path=db_path, settings=settings)
    panel.add_url_rule('/webhook/datafy', view_func=webhook.view_functions['receive'], methods=['POST'])
    return panel

# Gunicorn entry point used by Render.
app = create_render_app() if os.environ.get('RENDER') else None

if __name__ == '__main__':
    settings_path = ROOT / 'config.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig')) if settings_path.exists() else {}
    panel, webhook = create_apps(settings=settings)
    pp, wp = int(settings.get('panel_port',8765)), int(settings.get('webhook_port',8766))
    threading.Thread(target=lambda: serve(webhook,host='127.0.0.1',port=wp,threads=4),daemon=True).start()
    print(f'Painel: http://127.0.0.1:{pp} | Receptor local: http://127.0.0.1:{wp}/webhook/datafy', flush=True)
    print('Para encerrar, pressione Ctrl+C. Não publique a porta do painel.', flush=True)
    serve(panel,host='127.0.0.1',port=pp,threads=4)
