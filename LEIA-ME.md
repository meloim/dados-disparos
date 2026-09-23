# Relatórios locais da Datafy

Primeira versão em Python para Windows. Não envia mensagens e não acessa a conta da Datafy. Recebe novos eventos de um único número configurado e salva localmente em SQLite.

## Iniciar

1. Instale Python 3.11 ou superior pelo site oficial python.org, incluindo o Python Launcher (`py`).
2. Extraia a pasta inteira em um local de trabalho com acesso restrito ao administrativo.
3. Abra `Iniciar.bat`. Na primeira execução ele cria um ambiente e instala Flask, Waitress e openpyxl; requer internet. Mantenha a janela aberta.
4. Abra http://127.0.0.1:8765 no navegador. O painel já funciona para importar a base e exportar relatórios, mesmo sem o webhook configurado.

Para iniciar sem verificar dependências novamente: `.venv\Scripts\python.exe app.py` na pasta do programa.

## Configurar a Datafy

Copie `config.exemplo.json` para `config.json` (o iniciador faz isso se necessário). Edite no Bloco de Notas:

- `webhook_secret`: a NOVA chave de assinatura. Não reutilize a chave exposta na conversa. Também pode ser fornecida pela variável de ambiente DATAFY_WEBHOOK_SECRET.
- `phone_number_id`: identificador do número na Meta/Datafy, não é o telefone com DDD. É obrigatório para evitar misturar canais.
- `aceite` e `recusa`: listas de identificadores exatos dos botões (payload de template ou ID interativo). Se não houver ID, o programa usa o texto do botão. Os valores do exemplo precisam ser adaptados ao template real.

Reinicie o programa após editar. Não envie config.json junto com o sistema para outras pessoas. A chave nunca aparece no painel.

O receptor fica em **http://127.0.0.1:8766/webhook/datafy**. Este endereço local NÃO funciona no cadastro da Datafy. Ainda é necessário configurar um túnel/reverse proxy com HTTPS e endereço estável encaminhando somente para a porta 8766. Cadastre esse endereço HTTPS com `/webhook/datafy` e o evento `messages` na Datafy. Não publique a porta 8765: o painel foi feito para uso local, sem login remoto.

O programa valida HMAC-SHA256 sobre `timestamp.corpo_original`, recusa assinaturas inválidas e horários fora de cinco minutos e grava antes de confirmar o recebimento. Mantenha o relógio do Windows correto. Eventos repetidos não duplicam os resultados. O receptor ignora números diferentes do configurado.

## Capturar a campanha automaticamente

Não é necessário importar IDs. No painel, dê um nome à campanha e clique em **Ativar campanha** ANTES de iniciar os disparos na Datafy. Use esse número apenas para essa campanha durante a captura. Ao terminar os disparos, encerre a captura: entregas, leituras e respostas posteriores continuam ligadas aos envios registrados.

O programa registra telefone e ID automaticamente a partir do evento `sent`. O horário original desse evento define a campanha, inclusive quando o evento chega atrasado. Eventos `delivered` e `read` nunca são usados para presumir a campanha de um envio desconhecido. Um mesmo contato pode ter vários IDs de envio na mesma campanha, mas conta uma vez no resumo. Os resultados de entrega mostram o maior progresso alcançado por esse contato; as respostas consideram a mais recente. Os eventos completos aparecem no histórico.

Envios anteriores à ativação, sem status `sent`, ou feitos fora de uma campanha ficam sem vínculo, sinalizados no painel e exportados no histórico de todas as campanhas. Não são atribuídos automaticamente a uma campanha nova. Esses casos precisam de histórico adicional ou identificação manual; não há recuperação retroativa garantida.

Para adicionar nomes, opcionalmente importe CSV UTF-8 com `campanha;nome;telefone`. Use o mesmo nome de campanha e telefone com DDI e DDD. Reimportar não duplica contatos. A coluna antiga `mensagem_id` continua aceita para bases existentes, mas não é necessária no fluxo novo. A importação inteira é cancelada em caso de erro.

No painel, preencha as regras de aceite e recusa com os identificadores reais dos botões, um por linha. Você pode copiá-los de uma resposta de teste na fila de revisão. Essas regras ficam no banco local, prevalecem sobre config.json e valem para os próximos eventos sem reiniciar. Não adivinhe os identificadores pelos textos dos botões.

## Resultados e revisão

- Status de envio se liga pelo ID da mensagem enviada; resposta se liga pelo `context.id` quando disponível.
- Botões de templates (`button`) e respostas interativas (`interactive`) são interpretados. Texto livre vai para revisão, mesmo se disser “sim”, para evitar aceitar uma resposta fora de contexto.
- A resposta vinculada mais recente define o resultado. Uma resposta posterior desconhecida muda o resultado para revisão. Todas as respostas permanecem no histórico.
- Uma resposta sem contexto não entra nos totais de campanha até ser vinculada. A revisão permite selecionar somente contatos com o mesmo telefone e registra a alteração em auditoria local.
- Os estados de entrega não regridem ao receber eventos fora de ordem. “Lida” inclui entrega. “Não informado” não significa falha.
- O percentual tem como denominador os contatos da campanha (capturados automaticamente e importados, se houver); a importação por si só não comprova envio.
- Mídias aparecem pelo tipo, sem download/transcrição. A primeira versão não importa histórico antigo, não faz envio, não agenda relatórios nem suporta vários usuários remotos.

## Relatórios e backup

O Excel respeita a campanha selecionada e contém resumo, contatos e histórico. Se selecionar todas, inclui também eventos ainda sem vínculo. Textos recebidos são exportados como texto, não fórmulas.

Use “Salvar backup” para baixar uma cópia consistente do banco, inclusive com o programa aberto. Para migrar: feche o programa nas duas máquinas, copie a pasta e restaure o backup como `dados/relatorios.sqlite3` em uma instalação nova, antes de iniciar. Copie a configuração separadamente por um meio seguro. Guarde backups com acesso restrito, pois contêm telefones e respostas.

O programa e o túnel precisam continuar funcionando. Não há garantia de recuperar todos os eventos do período em que a máquina ficou desligada. Desativar suspensão e configurar início automático devem ser combinados com o TI. Não sobrescreva banco existente nem misture arquivos de backup com arquivos `-wal` de outra execução.

## Validação e limites

Execute `python -m unittest discover -s tests -v` para testes com dados fictícios. O teste local não comprova a conexão real. Depois da configuração HTTPS, ative uma campanha de teste, faça um envio autorizado, responda um botão e confira o painel e o Excel. O wamid será capturado automaticamente. Não há custo de licença neste programa; Datafy/Meta e eventual hospedagem/domínio continuam independentes.

## Endereço temporário de teste

Um Cloudflare Quick Tunnel pode encaminhar HTTPS para `http://127.0.0.1:8766`. Os eventos (telefones, respostas e status) passam pela Cloudflare. Use somente após autorizar esse tratamento. O endereço gerado muda entre execuções e não tem garantia de disponibilidade; destina-se a testes. Acrescente `/webhook/datafy` ao endereço gerado para cadastrá-lo na Datafy, com evento `messages`. Nunca aponte o túnel para 8765. A chave secreta fica local. Não há túnel incluído nem configurado automaticamente pelo iniciador.

Referências: https://developers.datafyapi.com.br/api-reference/whatsapp/webhooks/validar-assinatura e https://developers.datafyapi.com.br/api-reference/whatsapp/webhooks/eventos/mensagens
