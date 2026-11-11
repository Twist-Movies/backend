# Twist — Backend

API REST do **Twist**, uma plataforma social de filmes inspirada no Letterboxd (projeto acadêmico).
Os usuários pesquisam filmes no catálogo do [TMDB](https://www.themoviedb.org/), marcam como assistidos,
avaliam, escrevem comentários, montam playlists e seguem outros usuários.

**Stack:** Python 3.12 · Django 5.2 · Django REST Framework · SimpleJWT · PostgreSQL · Supabase Storage · drf-spectacular

---

## Sumário

- [Como rodar](#como-rodar)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Testes](#testes)
- [Documentação e coleções de requisições](#documentação-e-coleções-de-requisições)
- [Autenticação](#autenticação)
- [Endpoints](#endpoints)
- [Regras importantes](#regras-importantes)
- [Estrutura do projeto](#estrutura-do-projeto)

---

## Como rodar

```bash
# 1. Ambiente virtual e dependências
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 2. Variáveis de ambiente
cp .env.example .env            # preencha os valores (ver tabela abaixo)

# 3. Banco de dados (opcional: Postgres local via Docker)
docker compose up -d            # Postgres em localhost:5434 e pgAdmin em localhost:8081

# 4. Migrations e servidor
python manage.py migrate
python manage.py createcachetable   # tabela do cache `ratelimit` (contadores de limite)
python manage.py runserver
```

A API sobe em `http://localhost:8000` e o Swagger (só com `DEBUG=True` ou `ENABLE_DOCS=True`) em `http://localhost:8000/api/docs/`.

Para usar o Postgres do `docker-compose.yml`:

```
DATABASE_URL=postgres://twist_user:twist_password@localhost:5434/twist_db
```

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | sim | Chave secreta do Django |
| `DEBUG` | não | `True` em desenvolvimento (padrão `False`) |
| `DATABASE_URL` | sim | URL do PostgreSQL |
| `SUPABASE_URL` | sim | URL do projeto Supabase (upload de avatar e capa de playlist) |
| `SUPABASE_SERVICE_KEY` | sim | Service role key do Supabase |
| `TMDB_API_KEY` | sim | API Key (v3) **ou** Read Access Token (v4) do TMDB — [gerar aqui](https://www.themoviedb.org/settings/api) |
| `TMDB_LANGUAGE` | não | Idioma dos dados do TMDB (padrão `pt-BR`) |
| `TMDB_TIMEOUT_SECONDS` | não | Timeout das chamadas ao TMDB (padrão `5`) |
| `TMDB_CACHE_SECONDS` | não | Tempo de cache das respostas do TMDB (padrão `3600`) |
| `BREVO_API_KEY` | não | Chave da API do [Brevo](https://www.brevo.com) para enviar e-mails (não exige domínio próprio; o remetente precisa estar verificado no painel). Tem prioridade sobre o Resend |
| `RESEND_API_KEY` | não | Chave da API do [Resend](https://resend.com) para enviar e-mails. Sem ela, os e-mails são impressos no console |
| `DEFAULT_FROM_EMAIL` | não | Remetente. No Brevo precisa ser um remetente verificado; no Resend, de um domínio verificado (padrão de teste `Twist <onboarding@resend.dev>`) |
| `FRONTEND_URL` | não | URL do frontend usada no link de redefinição (padrão `http://localhost:5173`) |
| `PASSWORD_RESET_TIMEOUT` | não | Validade do link de redefinição, em segundos (padrão `3600`) |
| `EMAIL_BACKEND` | não | Sobrescreve o backend de e-mail (padrão: Brevo se houver `BREVO_API_KEY`, senão Resend se houver `RESEND_API_KEY`, senão console) |

> Nunca faça commit do `.env`. Ele já está no `.gitignore`.

## Testes

Os testes usam SQLite e simulam o TMDB e o Supabase, então não precisam de banco, internet nem chaves reais.

```bash
# Linux/macOS
DJANGO_SETTINGS_MODULE=config.settings.testing python manage.py test teste

# Windows (PowerShell)
$env:DJANGO_SETTINGS_MODULE="config.settings.testing"; python manage.py test teste
```

## Documentação e coleções de requisições

| Onde | O que é |
|---|---|
| `http://localhost:8000/api/docs/` | Swagger UI (gerado automaticamente) |
| `http://localhost:8000/api/redoc/` | ReDoc |
| `http://localhost:8000/api/schema/` | Schema OpenAPI em YAML |
| [`api-requests/`](api-requests/) | Arquivos `.http` para rodar direto no VS Code ([REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client)) ou IntelliJ |
| [`postman/`](postman/) | Coleção e ambiente prontos para importar no Postman |

### Postman

1. No Postman, clique em **Import** e selecione os dois arquivos da pasta [`postman/`](postman/).
2. No canto superior direito, selecione o ambiente **Twist - Local**.
3. Rode **Autenticação → Cadastro** e depois **Login**. O token é salvo sozinho e todas as outras requisições já saem autenticadas.
4. Para rodar tudo de uma vez: clique com o botão direito na coleção → **Run collection**.

## Autenticação

Autenticação via **JWT** (SimpleJWT). O login aceita **e-mail ou username** no campo `identifier` e devolve no corpo apenas o access token (vida de 5 min):

```json
{ "access": "<token>", "username": "marcos" }
```

O **refresh token** (1 dia, sem rotação) **não vai no corpo**: é entregue em um cookie `HttpOnly` (`twist_refresh`, `Path=/api/accounts/`), inacessível ao JavaScript (mitiga roubo por XSS). O front guarda o access só em memória. Envie o access nas rotas protegidas:

```
Authorization: Bearer <access>
```

- `POST /api/accounts/token/refresh/` lê o refresh do cookie e devolve `{ "access": "<token>" }`. Quando o refresh vem do cookie, é obrigatório o header `X-Twist-Client: web` (proteção CSRF: header customizado força o preflight CORS), senão `403`. Refresh ausente/inválido/revogado: `401` e o cookie é apagado. Clientes não-navegador (curl/Postman) podem enviar `{"refresh": "..."}` no corpo (sem exigir o header).
- `POST /api/accounts/logout/` revoga o refresh (blacklist, do cookie com o header ou do corpo) e sempre apaga o cookie.
- Redefinir a senha (`password-reset/confirm/`) e excluir a conta (`DELETE /api/users/me/`) também apagam o cookie.
- CORS: `CORS_ALLOW_CREDENTIALS=True` e `X-Twist-Client` liberado nos headers; as origens continuam uma lista fixa.

Variáveis do cookie (todas opcionais):

| Variável | Padrão | Descrição |
|---|---|---|
| `REFRESH_COOKIE_NAME` | `twist_refresh` | Nome do cookie |
| `REFRESH_COOKIE_SECURE` | `False` se `DEBUG`, senão `True` (sempre `True` em produção) | Atributo `Secure` |
| `REFRESH_COOKIE_SAMESITE` | `Lax` | `Lax`, `Strict` ou `None` |

> **Produção:** se o front e a API estiverem em domínios diferentes (ex.: dois serviços no Render), o cookie é cross-site e só funciona com `REFRESH_COOKIE_SAMESITE=None` e `Secure` (HTTPS). O ideal é servir `/api` pelo mesmo domínio do front (rewrite/proxy), mantendo `Lax`.

## Limites de requisição (429)

Excedido o limite, a API responde `429` com o header `Retry-After`. Todas as taxas são configuráveis por variável de ambiente (formato `N/min`, `N/hour`...):

| Variável | Padrão | Escopo |
|---|---|---|
| `THROTTLE_ANON` / `THROTTLE_USER` | `240/min` / `600/min` | global, por IP (anônimos) / por usuário |
| `THROTTLE_LOGIN` | `20/min` | login, por IP |
| `LOGIN_FAILURE_LIMIT` / `LOGIN_FAILURE_WINDOW` | `8` / `900` (s) | falhas de login por conta (`identifier`, sem diferenciar caixa); zera no sucesso |
| `THROTTLE_REGISTER` | `5/hour` | cadastro, por IP |
| `THROTTLE_TMDB` | `120/min` | rotas que chamam o TMDB (busca, discover, trending, detalhe, recomendações, pessoas), por IP |
| `THROTTLE_PASSWORD_RESET_REQUEST` / `_CONFIRM` | `5/hour` / `10/hour` | reset de senha, por IP |
| `NUM_PROXIES` | `1` | proxies na frente da API (Render = 1); o IP é o último do `X-Forwarded-For`, então valores forjados à esquerda não burlam os limites |

Os contadores ficam no cache `ratelimit` (`DatabaseCache`, tabela `twist_ratelimit`), compartilhado entre processos; crie a tabela com `python manage.py createcachetable` (o `build.sh` já faz isso). O cache `default` (TMDB) continua em memória.

## Produção (Render)

`config.settings.production` é o padrão de `wsgi.py`/`asgi.py` (o `manage.py` continua em `development`). Ele ativa `SECURE_PROXY_SSL_HEADER` (`X-Forwarded-Proto`), redirecionamento para HTTPS (`SECURE_SSL_REDIRECT`, padrão `True`; `/healthz/` é isento), HSTS (`SECURE_HSTS_SECONDS`, padrão `3600`, sem subdomínios/preload), cookies Secure, `nosniff` e `Referrer-Policy: same-origin`.

| Variável | Padrão em produção | Descrição |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `https://twist-frontend.onrender.com` (em dev: `http://localhost:5173`) | Origens do front, separadas por vírgula (sem localhost em produção) |
| `CSRF_TRUSTED_ORIGINS` | vazio (+ `https://$RENDER_EXTERNAL_HOSTNAME`) | Origens confiáveis para CSRF |
| `REFRESH_COOKIE_SAMESITE` | `None` | Front e API em domínios `onrender.com` diferentes são cross-site. Com rewrite de `/api` no domínio do front, use `Lax` |
| `ENABLE_DOCS` | `False` | Swagger/Redoc/schema (`/api/docs/`, `/api/redoc/`, `/api/schema/`) só existem com `DEBUG` ou `ENABLE_DOCS=True` |
| `ADMIN_URL` | `admin/` | Caminho do Django admin (troque por algo difícil de adivinhar) |
| `PASSWORD_RESET_EMAIL_ASYNC` | `True` fora de `DEBUG` | Envia o e-mail de reset em thread daemon; falhas só são logadas |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | `True`, `3600` | Ver acima |

Health check do Render: `GET /healthz/` (200 `ok`, sem auth, sem throttle, sem banco). Os caches têm teto de entradas (`ratelimit`: 200000, `default`: 5000). Erros do TMDB nunca expõem detalhes ao cliente (`503 Serviço de filmes indisponível no momento.` / `404 Filme não encontrado.`); o detalhe vai para o log. O bloqueio de login por falhas é por conta + IP. O logout não exige access token válido. Uploads de imagem (avatar/capa): só JPEG/PNG/WebP reais (conferidos com Pillow), até 4096x4096 e 5MB; são reencodados sem EXIF; falha do storage devolve `503`.

## Contas: e-mail, username e nomes reservados

E-mail é salvo em minúsculas; e-mail e username são únicos sem diferenciar caixa e o login por e-mail ou username também ignora a caixa. Nomes reservados (sem diferenciar caixa) não podem ser usados no cadastro nem no `PATCH /api/users/me/`: `twist`, `admin`, `administrator`, `root`, `suporte`, `support`, `staff`, `moderador`, `moderator`, `api`, `null`, `undefined`, `system`, `oficial`. A migração `accounts.0002` põe e-mails existentes em minúsculas, pulando (e logando) os que gerariam conflito.

## Endpoints


### Autenticação — `/api/accounts/`

| Método | Rota | Login | Descrição |
|---|---|---|---|
| POST | `/api/accounts/register/` | não | Cadastro (`multipart/form-data`, aceita `avatar`) |
| POST | `/api/accounts/login/` | não | Login com `identifier` (e-mail ou username) e `password` |
| POST | `/api/accounts/token/refresh/` | não | Novo access token a partir do refresh (cookie `twist_refresh` + header `X-Twist-Client: web`, ou `refresh` no corpo) |
| POST | `/api/accounts/logout/` | sim | Revoga o refresh (cookie ou corpo) e apaga o cookie |
| POST | `/api/accounts/password-reset/` | não | Solicita a redefinição de senha (`email`). Sempre `200`, exista ou não a conta; limite de 5/hora por IP |
| POST | `/api/accounts/password-reset/confirm/` | não | Define a nova senha (`uid`, `token`, `new_password`). Link inválido/expirado: `400`; revoga todos os refresh tokens; limite de 10/hora por IP |

#### Recuperação de senha e e-mail

O e-mail leva o link `{FRONTEND_URL}/redefinir-senha/{uid}/{token}`, válido por `PASSWORD_RESET_TIMEOUT` segundos e de uso único (o token deixa de valer quando a senha muda). O envio é feito pela API do Brevo ou do Resend (`apps/common/email.py`); falhas de envio são apenas logadas.

> Com o remetente de teste `onboarding@resend.dev`, o Resend só entrega para o e-mail dono da conta Resend. Para enviar a qualquer usuário é preciso verificar um domínio no Resend e usá-lo em `DEFAULT_FROM_EMAIL`.

### Usuários — `/api/users/`

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/users/me/` | sim | Dados do usuário logado |
| PATCH | `/api/users/me/` | sim | Edita o perfil (menos a senha). Trocar o `email` exige `current_password`; a troca revoga todos os refresh tokens, apaga o cookie e avisa o e-mail antigo |
| DELETE | `/api/users/me/` | sim | Exclui a conta (confirmar com `{"username": "...", "password": "..."}`) |
| POST | `/api/users/{id}/follow/` | sim | Segue o usuário |
| DELETE | `/api/users/{id}/follow/` | sim | Deixa de seguir |
| GET | `/api/users/{id}/followers/` | não | Seguidores do usuário |
| GET | `/api/users/{id}/following/` | não | Quem o usuário segue |
| GET | `/api/users/{id}/reviews/` | não | Comentários ativos do usuário (paginado, mais recentes primeiro) |
| GET | `/api/users/search/?q=ma` | não | Busca por username ou nome (mín. 2 caracteres, paginado; sem e-mail) |

### Filmes — `/api/movies/`

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/movies/search/?q=matrix&page=1` | não | Busca no TMDB |
| GET | `/api/movies/discover/` | não | Catálogo filtrável (`sort`, `genre`, `decade`, `runtime_*`, `rating_min`, `page`); itens com `overview` e `backdrop_path` |
| GET | `/api/movies/trending/?page=1` | não | Filmes em alta na semana (TMDB), mesmo formato da busca |
| GET | `/api/movies/{tmdb_id}/recommendations/?page=1` | não | Recomendações do TMDB (cai para "similares" se vazio), mesmo formato da busca |
| GET | `/api/people/{tmdb_id}/` | não | Pessoa: `id, name, biography, birthday, place_of_birth, known_for_department, profile_path, movies` (até 20 filmes por popularidade) |
| GET | `/api/movies/{tmdb_id}/` | não | Detalhes (elenco e equipe com `id`, `genres` e `genres_info`, `trailer` = chave do YouTube ou `null`, classificação), contadores do Twist (`approval_percent` e `approval_votes` em `stats`) e, se logado, o estado do usuário |
| POST | `/api/movies/{tmdb_id}/watch/` | sim | Marca como assistido |
| DELETE | `/api/movies/{tmdb_id}/watch/` | sim | Remove de assistidos |
| POST | `/api/movies/{tmdb_id}/watchlist/` | sim | Adiciona à lista "Quero assistir" |
| DELETE | `/api/movies/{tmdb_id}/watchlist/` | sim | Remove da lista |
| PUT/PATCH | `/api/movies/{tmdb_id}/rating/` | sim | Avalia ou altera a nota: `{"stars": 0.5..5}` (passos de 0,5; sempre devolvido como número, ex. `4.5`) |
| DELETE | `/api/movies/{tmdb_id}/rating/` | sim | Remove a avaliação |
| PUT | `/api/movies/{tmdb_id}/reaction/` | sim | Curte ou dá deslike: `{"reaction": "LIKE" \| "DISLIKE"}` |
| DELETE | `/api/movies/{tmdb_id}/reaction/` | sim | Remove a reação |

### Comentários

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/movies/{tmdb_id}/reviews/` | não | Comentários do filme (mais recentes primeiro) |
| POST | `/api/movies/{tmdb_id}/reviews/` | sim | Cria comentário: `{"content": "...", "contains_spoiler": false}` |
| GET | `/api/reviews/{id}/` | não | Consulta um comentário |
| PATCH | `/api/reviews/{id}/` | sim | Edita (só o autor) |
| DELETE | `/api/reviews/{id}/` | sim | Exclui (só o autor) |
| POST | `/api/reviews/{id}/like/` | sim | Curte o comentário |
| DELETE | `/api/reviews/{id}/like/` | sim | Remove a curtida |

### Feed

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/feed/` | sim | Comentários ativos de quem o usuário segue, mais recentes primeiro (paginado, 20 por página; inclui o filme) |

### Playlists

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/playlists/` | sim | Playlists do usuário logado |
| POST | `/api/playlists/` | sim | Cria playlist (`name`, `description`, `is_public`, `cover` opcional) |
| GET | `/api/playlists/official/` | não | Playlists públicas da conta oficial `twist` (paginado) |
| GET | `/api/playlists/{id}/` | não | Detalhes com os filmes (privada só para o dono) |
| PATCH | `/api/playlists/{id}/` | sim | Edita (só o dono) |
| DELETE | `/api/playlists/{id}/` | sim | Exclui (só o dono) |
| POST | `/api/playlists/{id}/movies/` | sim | Adiciona filme: `{"tmdb_id": 603}` |
| DELETE | `/api/playlists/{id}/movies/{tmdb_id}/` | sim | Remove o filme |

As playlists oficiais são criadas por `python manage.py seed_listas_oficiais` (idempotente; cria a conta staff `twist` e consulta o TMDB, então exige `TMDB_API_KEY`). Se já existir um usuário `twist` que não seja a conta staff com senha inutilizável criada pelo comando, ele aborta com erro em vez de publicar listas nessa conta.

## Regras importantes

- **`{tmdb_id}`** nas rotas de filme é o **id do TMDB**, o mesmo que vem na busca. Na primeira interação o filme é salvo no banco local automaticamente, sem duplicar.
- **Paginação:** listagens retornam `{"count", "next", "previous", "results"}` com 20 itens por página (`?page=2`).
- **Reações:** o usuário tem no máximo uma reação por filme. Enviar `DISLIKE` depois de `LIKE` troca a reação.
- **Comentários:** um comentário ativo por usuário e filme. A exclusão é lógica, então dá para escrever um novo depois de excluir.
- **Playlists:** o mesmo filme não entra duas vezes; os filmes ficam na ordem em que foram adicionados (`position`).
- **Erros do TMDB:** filme inexistente retorna `404`; TMDB fora do ar ou limite de requisições retorna `503`.
- **Respostas `POST` idempotentes:** marcar como assistido, adicionar à watchlist e curtir comentário retornam `201` na primeira vez e `200` se já existia.

## Estrutura do projeto

```
api-requests/   requisições .http de exemplo
apps/
  accounts/     usuários, autenticação e seguidores
  common/       upload de imagens (Supabase) e validadores
  movies/       filmes (TMDB), avaliações, reações, comentários e playlists
    tmdb.py       cliente da API do TMDB (cache e tratamento de erros)
    services.py   sincronização do filme local e contadores
config/         settings (base, development, production, testing) e urls
postman/        coleção e ambiente do Postman
teste/          testes automatizados
```
