# Twist — Backend

API REST do **Twist**, uma plataforma social de filmes inspirada no Letterboxd (projeto acadêmico).
Os usuários pesquisam filmes no catálogo do [TMDB](https://www.themoviedb.org/), marcam como assistidos,
avaliam, escrevem resenhas, montam playlists e seguem outros usuários.

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
python manage.py runserver
```

A API sobe em `http://localhost:8000` e o Swagger em `http://localhost:8000/api/docs/`.

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

Autenticação via **JWT** (SimpleJWT). O login aceita **e-mail ou username** no campo `identifier` e devolve:

```json
{ "access": "<token>", "refresh": "<token>", "username": "marcos" }
```

Envie o access token nas rotas protegidas:

```
Authorization: Bearer <access>
```

Quando o access expirar, gere outro em `POST /api/accounts/token/refresh/`. O logout revoga o refresh token (blacklist).

## Endpoints


### Autenticação — `/api/accounts/`

| Método | Rota | Login | Descrição |
|---|---|---|---|
| POST | `/api/accounts/register/` | não | Cadastro (`multipart/form-data`, aceita `avatar`) |
| POST | `/api/accounts/login/` | não | Login com `identifier` (e-mail ou username) e `password` |
| POST | `/api/accounts/token/refresh/` | não | Novo access token a partir do `refresh` |
| POST | `/api/accounts/logout/` | sim | Revoga o `refresh` informado |

### Usuários — `/api/users/`

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/users/me/` | sim | Dados do usuário logado |
| PATCH | `/api/users/me/` | sim | Edita o perfil (menos a senha) |
| DELETE | `/api/users/me/` | sim | Exclui a conta (confirmar com `{"username": "..."}`) |
| POST | `/api/users/{id}/follow/` | sim | Segue o usuário |
| DELETE | `/api/users/{id}/follow/` | sim | Deixa de seguir |
| GET | `/api/users/{id}/followers/` | não | Seguidores do usuário |
| GET | `/api/users/{id}/following/` | não | Quem o usuário segue |

### Filmes — `/api/movies/`

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/movies/search/?q=matrix&page=1` | não | Busca no TMDB |
| GET | `/api/movies/{tmdb_id}/` | não | Detalhes (elenco, equipe, gêneros, classificação), contadores do Twist e, se logado, o estado do usuário |
| POST | `/api/movies/{tmdb_id}/watch/` | sim | Marca como assistido |
| DELETE | `/api/movies/{tmdb_id}/watch/` | sim | Remove de assistidos |
| POST | `/api/movies/{tmdb_id}/watchlist/` | sim | Adiciona à lista "Quero assistir" |
| DELETE | `/api/movies/{tmdb_id}/watchlist/` | sim | Remove da lista |
| PUT/PATCH | `/api/movies/{tmdb_id}/rating/` | sim | Avalia ou altera a nota: `{"stars": 1..5}` |
| DELETE | `/api/movies/{tmdb_id}/rating/` | sim | Remove a avaliação |
| PUT | `/api/movies/{tmdb_id}/reaction/` | sim | Curte ou dá deslike: `{"reaction": "LIKE" \| "DISLIKE"}` |
| DELETE | `/api/movies/{tmdb_id}/reaction/` | sim | Remove a reação |

### Resenhas

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/movies/{tmdb_id}/reviews/` | não | Resenhas do filme (mais recentes primeiro) |
| POST | `/api/movies/{tmdb_id}/reviews/` | sim | Cria resenha: `{"content": "...", "contains_spoiler": false}` |
| GET | `/api/reviews/{id}/` | não | Consulta uma resenha |
| PATCH | `/api/reviews/{id}/` | sim | Edita (só o autor) |
| DELETE | `/api/reviews/{id}/` | sim | Exclui (só o autor) |
| POST | `/api/reviews/{id}/like/` | sim | Curte a resenha |
| DELETE | `/api/reviews/{id}/like/` | sim | Remove a curtida |

### Playlists

| Método | Rota | Login | Descrição |
|---|---|---|---|
| GET | `/api/playlists/` | sim | Playlists do usuário logado |
| POST | `/api/playlists/` | sim | Cria playlist (`name`, `description`, `is_public`, `cover` opcional) |
| GET | `/api/playlists/{id}/` | não | Detalhes com os filmes (privada só para o dono) |
| PATCH | `/api/playlists/{id}/` | sim | Edita (só o dono) |
| DELETE | `/api/playlists/{id}/` | sim | Exclui (só o dono) |
| POST | `/api/playlists/{id}/movies/` | sim | Adiciona filme: `{"tmdb_id": 603}` |
| DELETE | `/api/playlists/{id}/movies/{tmdb_id}/` | sim | Remove o filme |

## Regras importantes

- **`{tmdb_id}`** nas rotas de filme é o **id do TMDB**, o mesmo que vem na busca. Na primeira interação o filme é salvo no banco local automaticamente, sem duplicar.
- **Paginação:** listagens retornam `{"count", "next", "previous", "results"}` com 20 itens por página (`?page=2`).
- **Reações:** o usuário tem no máximo uma reação por filme. Enviar `DISLIKE` depois de `LIKE` troca a reação.
- **Resenhas:** uma resenha ativa por usuário e filme. A exclusão é lógica, então dá para escrever uma nova depois de excluir.
- **Playlists:** o mesmo filme não entra duas vezes; os filmes ficam na ordem em que foram adicionados (`position`).
- **Erros do TMDB:** filme inexistente retorna `404`; TMDB fora do ar ou limite de requisições retorna `503`.
- **Respostas `POST` idempotentes:** marcar como assistido, adicionar à watchlist e curtir resenha retornam `201` na primeira vez e `200` se já existia.

## Estrutura do projeto

```
api-requests/   requisições .http de exemplo
apps/
  accounts/     usuários, autenticação e seguidores
  common/       upload de imagens (Supabase) e validadores
  movies/       filmes (TMDB), avaliações, reações, resenhas e playlists
    tmdb.py       cliente da API do TMDB (cache e tratamento de erros)
    services.py   sincronização do filme local e contadores
config/         settings (base, development, production, testing) e urls
postman/        coleção e ambiente do Postman
teste/          testes automatizados
```
