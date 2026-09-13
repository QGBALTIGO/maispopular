# Vitrine azul, preços e avaliações

Referência visual inspecionada em 13/09/2026: https://contingenciamaxima.com.br/.
Implementação própria adaptada à Mais Popular: hero, destaques, cards, menu,
busca, carteira e avaliações. Não incorpora código, avaliações, números de
clientes, descontos ou programa de afiliados da referência.

## Preços

- Administração → Gerenciar preços do catálogo: regra geral, preço por serviço
  ou retorno à regra geral. Alterações exigem motivo e confirmação e ficam no
  histórico. A regra inicial continua custo × 2.
- Preços unitários preservam frações de centavo. Somente o total é arredondado
  para centavos. Quantidade mínima e valor final permanecem visíveis.
- Cotações antigas expiram se a política muda; uma revisão é validada dentro
  da transação de débito. Pedidos já pagos não são recalculados.
- Preços personalizados usam identidade do serviço para evitar aplicar um
  preço antigo quando o fornecedor reutiliza um código.

## Avaliações

- Apenas o titular de um pedido concluído e debitado pode publicar.
- Uma avaliação por pedido, com apelido público, nota 1–5, comentário e
  consentimento explícito. Repetir o mesmo envio é idempotente.
- Média e contagem são reais; notas baixas também são incluídas. Nenhum
  depoimento é pré-preenchido em produção. Estado vazio sem nota fictícia.
- Nenhum ID Telegram, destino, ID do pedido ou nome da conta é exposto na
  listagem. Comentários são renderizados como texto, nunca HTML.
- A prévia `deploy/preview_ui.py` usa SQLite temporário e serviços de pagamento
  e entrega simulados. O pedido de QA nela criado jamais vai à produção.

## Arte gerada

Modo: ferramenta integrada image_gen (não CLI). Arquivos finais:

- `webapp_static/banners/social-blue-v2.png`
- `webapp_static/banners/streaming-blue-v2.png`

Prompt final 1:

Use case: ads-marketing. Asset type: wide 16:9 digital storefront product-card
campaign art for Mais Popular, also used as hero feature. Create a polished
Brazilian digital-services shop banner, black backdrop with electric royal BLUE
and cyan 3D lighting, angular diagonal chrome blue ribbons, subtle halftone
texture and floating glass notification icons (heart, follower silhouette, play
symbol). A large glossy Instagram app logo on the LEFT, surrounded by a few
blue notification tiles. On the RIGHT, very large bold condensed slightly
italic white text 'REDES' then electric blue 'SOCIAIS'; below, small clear white
text 'MAIS POPULAR'. Composition must read on a mobile product thumbnail;
generous safe margins, no tiny text. The style is energetic professional
gaming/digital storefront artwork, not a website screenshot, not a UI mockup.
Royal blue instead of purple as dominant lighting. Keep Instagram logo
recognizable in its original gradient. No discounts, no prices, no customer
counts, no delivery guarantees, no fake ratings, no other store names, no
watermark. Landscape 1536x864.

Prompt final 2:

Use case: ads-marketing. Asset type: wide 16:9 product card campaign banner for
Brazilian store Mais Popular. Black backdrop with electric royal BLUE 3D
diagonal chrome ribbons and cyan neon rim lights, angular composition, subtle
blue halftone particles. A large glossy tilted black movie-streaming tile on
the left with a dimensional red Netflix N; smaller blue play triangle glass
tile below. On the RIGHT huge very readable bold condensed slightly italic
white 'STREAMING', next line electric blue 'E APPS', small white spaced 'MAIS
POPULAR'. Professional energetic Brazilian digital storefront banner art,
thumbnail readable, consistent with neon blue social-media retail banners. No
website UI. No purple dominant lighting, no prices, no discount, no guarantees,
no customer counts, no subscription duration, no brand affiliation claim, no
other store names. Landscape1536x864. Keep margins generous.

As logos identificam os serviços; a loja permanece independente das marcas.
