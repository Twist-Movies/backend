# Requisições `.http`

Exemplos prontos de todas as rotas da API, um arquivo por recurso.

## Como usar

- **VS Code:** instale a extensão [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client) e clique em `Send Request` acima de cada requisição.
- **IntelliJ / PyCharm:** suporte nativo; clique no botão de play ao lado de cada requisição.

Com o servidor rodando (`python manage.py runserver`):

1. Rode o **cadastro** em `accounts.http` uma vez, para criar o usuário `twist_demo`.
2. Em cada arquivo, rode primeiro o bloco **Login**. Ele guarda o token e as outras requisições do arquivo já saem autenticadas.

| Arquivo | Conteúdo |
|---|---|
| `accounts.http` | cadastro, login, refresh e logout |
| `users.http` | perfil, seguir/deixar de seguir, seguidores |
| `movies.http` | busca no TMDB, detalhes, assistido, watchlist, nota e reação |
| `reviews.http` | resenhas e curtidas |
| `playlists.http` | playlists e filmes da playlist |
