# Ligar o robô de atendimento ao Disparos Construir

A Datafy avisa o painel **que** o robô respondeu (enviado, entregue, lido), mas **não manda o texto**. Para o texto aparecer na aba **Conversas**, o robô manda uma cópia de cada mensagem que enviar.

## 1. No painel (Railway)

Crie a variável **`ROBO_API_TOKEN`** no serviço do painel com um texto longo e aleatório. Para gerar um:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Aplique o deploy. Em **Configurações → Servidor**, a linha "Texto das respostas do robô" deve ficar com ✓.

## 2. No robô

Coloque o **mesmo token** numa variável do robô (ex.: `PAINEL_TOKEN`) e, **logo depois de cada mensagem enviada com sucesso pela Datafy**, faça esta chamada:

```
POST https://datafy-relatorios-production.up.railway.app/api/robo/mensagens
Authorization: Bearer <PAINEL_TOKEN>
Content-Type: application/json

{
  "telefone": "5583991111111",
  "texto": "O evento começa às 14h, no auditório principal.",
  "wamid": "wamid.HBgM...",            // ID que a Datafy devolveu no envio (recomendado)
  "enviado_em": "2026-11-18T14:32:00-03:00",   // opcional: ISO, segundos ou milissegundos
  "transferido_para_humano": false     // true quando o robô passar a conversa para a equipe
}
```

- Pode mandar **uma mensagem ou uma lista** de mensagens.
- Com o **`wamid`**, o texto entra no mesmo balão do status (entregue/lida). Sem ele, a mensagem aparece pelo horário.
- Mandar a mesma cópia de novo **não duplica**.
- **Não deixe o robô travar se o painel estiver fora do ar**: faça a chamada com tempo limite curto e ignore erros.

### Exemplo em Node/TypeScript

```ts
async function copiarParaPainel(telefone: string, texto: string, wamid?: string, transferido = false) {
  try {
    await fetch('https://datafy-relatorios-production.up.railway.app/api/robo/mensagens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${process.env.PAINEL_TOKEN}` },
      body: JSON.stringify({ telefone, texto, wamid, enviado_em: Date.now(), transferido_para_humano: transferido }),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    // O painel é só para acompanhamento: falha aqui nunca pode impedir o atendimento.
  }
}
```

### Exemplo em Python

```python
import os, time, requests

def copiar_para_painel(telefone, texto, wamid=None, transferido=False):
    try:
        requests.post('https://datafy-relatorios-production.up.railway.app/api/robo/mensagens',
                      headers={'Authorization': f"Bearer {os.environ['PAINEL_TOKEN']}"},
                      json={'telefone': telefone, 'texto': texto, 'wamid': wamid,
                            'enviado_em': int(time.time()), 'transferido_para_humano': transferido},
                      timeout=5)
    except Exception:
        pass  # Falha no painel nunca pode impedir o atendimento.
```

## Texto pronto para pedir ao Codex (ou a quem mantém o robô)

> No robô de atendimento, depois de **cada mensagem enviada com sucesso** pela API da Datafy, envie uma cópia para o painel de acompanhamento: `POST https://datafy-relatorios-production.up.railway.app/api/robo/mensagens` com o cabeçalho `Authorization: Bearer ${PAINEL_TOKEN}` e o JSON `{"telefone", "texto", "wamid" (o id retornado pela Datafy no envio), "enviado_em", "transferido_para_humano"}`. Use `transferido_para_humano: true` na mensagem em que o robô passa a conversa para a equipe. A chamada deve ter tempo limite de 5 s e qualquer erro deve ser ignorado (não pode atrapalhar o atendimento). Leia o token da variável de ambiente `PAINEL_TOKEN`.
