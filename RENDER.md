# Publicar na Render

O projeto inclui `render.yaml`, que cria uma aplicação web e um PostgreSQL. A Render fornece uma URL HTTPS no formato `https://datafy-relatorios-xxxx.onrender.com`.

## Antes de publicar

1. Coloque esta pasta em um repositório privado no GitHub. Não envie `config.json`, a pasta `dados` nem arquivos de backup; o `.gitignore` já os exclui.
2. Gere uma nova chave de webhook na Datafy imediatamente antes da configuração. Guarde-a somente nas variáveis secretas da Render.
3. Escolha uma senha forte e exclusiva para o painel.

## Criar pela Blueprint

1. Na Render, escolha **New > Blueprint** e conecte o repositório.
2. A Render lerá `render.yaml` e mostrará o serviço `datafy-relatorios` e o banco `datafy-relatorios-db`.
3. Preencha os valores solicitados:
   - `PANEL_PASSWORD`: senha do painel.
   - `DATAFY_WEBHOOK_SECRET`: nova chave `whsec_...` da Datafy.
   - `DATAFY_PHONE_NUMBER_ID`: `1296717156847615`.
4. Confirme a criação e espere o deploy terminar.
5. Abra a URL da aplicação. O usuário inicial é `admin`; a senha é a definida em `PANEL_PASSWORD`.
6. Na Datafy, cadastre `https://SUA-URL.onrender.com/webhook/datafy` e selecione somente o evento `messages` para o fluxo atual.
7. No painel, ative uma campanha de teste, envie uma mensagem autorizada, responda ao botão e confira a atualização.

## Limitação do plano grátis

O plano gratuito é adequado apenas para teste. A Render suspende a aplicação após 15 minutos sem tráfego e informa que a reativação pode levar cerca de um minuto. A Datafy exige resposta do webhook em até 20 segundos; portanto, o primeiro evento após a suspensão pode falhar ou depender de uma tentativa posterior da Datafy. Não trate o plano grátis como coleta confiável.

O PostgreSQL grátis expira 30 dias após a criação e é apagado depois do período de carência se não for atualizado. Ele também não inclui backups. Baixe o backup pelo painel com frequência durante o teste.

Para uso diário, coloque a aplicação em um plano que não suspenda e o PostgreSQL em um plano persistente. Mantenha os dois na mesma região. A URL do webhook permanece a mesma ao mudar o plano.

## Variáveis e segurança

- `SECRET_KEY` é gerada automaticamente pela Render e mantém as sessões do painel válidas entre reinícios.
- `DATABASE_URL` é ligada automaticamente ao PostgreSQL pela Blueprint.
- A chave da Datafy e a senha do painel não ficam no código nem no ZIP.
- `/healthz` é público e retorna apenas `{"ok": true}`.
- `/webhook/datafy` é público, mas aceita somente eventos com assinatura HMAC válida, timestamp recente e Phone Number ID configurado.
- Todas as demais telas exigem login.

## Atualizações

Depois de alterar o código, envie a nova versão ao mesmo repositório. A Render fará um novo deploy sem trocar a URL. Antes de mudanças importantes, baixe o backup pelo painel.
