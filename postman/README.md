# Postman

| Arquivo | O que é |
|---|---|
| `Twist.postman_collection.json` | Coleção com todas as rotas da API, organizadas por pasta |
| `Twist.local.postman_environment.json` | Ambiente com `base_url = http://localhost:8000` |

## Como importar

1. Com o servidor rodando (`python manage.py runserver`), abra o Postman e clique em **Import**.
2. Arraste os dois arquivos desta pasta.
3. No canto superior direito, selecione o ambiente **Twist - Local**.
4. Rode **Autenticação → Cadastro** e depois **Login**. Os tokens ficam salvos nas variáveis da coleção e
   todas as outras requisições já saem autenticadas.

Para rodar tudo de uma vez, clique com o botão direito na coleção e escolha **Run collection**.
A pasta **Sessão e conta** fica por último e exclui o usuário de teste, então a coleção pode ser rodada de novo.

## Variáveis da coleção

| Variável | Valor padrão | Uso |
|---|---|---|
| `username` / `password` | `twist_demo` / `Tw1st!Senha#Forte` | Usuário criado no cadastro |
| `tmdb_id` | `603` (Matrix) | Filme usado nas rotas de filmes, resenhas e playlists |
| `second_tmdb_id` | `157336` (Interestelar) | Segundo filme da playlist |
| `access_token`, `refresh_token` | preenchidos pelo login | Autenticação |
| `user_id`, `other_user_id`, `review_id`, `playlist_id` | preenchidos pelas requisições | Ids usados nas rotas seguintes |

Para usar outro servidor (por exemplo, o de produção), duplique o ambiente e altere `base_url`.
