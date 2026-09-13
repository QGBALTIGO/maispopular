# Banners e catálogo compacto — 13/09/2026

Menu → Administração → Gerenciar banners da loja.

Três posições do carrossel podem ser alteradas pelo admin. PNG/JPG/WebP até
4 MB, sem animação; até 6000 px por lado / 16 MP. Imagem horizontal 16:9
recomendada. A prévia mostra a mesma proporção e enquadramento da vitrine.

Opções: imagem inteira sem cortes ou preenchimento, centro/topo/base, título
acessível e destino do toque (redes, streaming, apps, carteira ou suporte).
O botão de restauração repõe imagem e configuração originais da posição.
Uploads são validados pela assinatura e decodificação real, não pela extensão.
SVG e URLs externas não são aceitos. Não há busca de imagem remota.

Arquivos são armazenados como BLOB em `shop_banners`, no mesmo SQLite com WAL
dos demais dados. Publicação e revisão são atômicas; uma edição antiga não
sobrescreve outra sessão. Não exige reiniciar serviços. Voltar ao catálogo
ou reabrir o Mini App recarrega a configuração.

Foi removida da interface a apresentação inicial, os cards flutuantes, a
chamada promocional de carteira e as avaliações (incluindo formulário nos
pedidos e atalho do menu). Dados históricos não foram apagados; as rotas
legadas autenticadas de avaliações permanecem por compatibilidade.

Redes sociais mostram nome, famílias disponíveis, menor preço unitário atual
e quantidade mínima do serviço de referência. Pacotes usam preço por pacote.
Título e descrição dos cards não reservam mais alturas vazias; o preço não é
empurrado para baixo por margem automática.

Verificação: upload no navegador em base temporária → API autenticada → BLOB
persistido → URL local da imagem → carrossel com enquadramento publicado.
Testes cobrem restauração, concorrência, permissões, formatos e limites.
Nenhum banner de QA é enviado à produção.
