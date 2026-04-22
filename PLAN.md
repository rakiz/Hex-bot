# Plan d'évolution — Hex Bot

## Simplifications retenues

- **Un seul workspace Slack** (usage interne MongoDB) : pas de flow d'installation multi-tenant,
  le bot token reste une variable d'environnement.
- **SQLite embarqué** à la place d'un serveur de base de données : un seul fichier sur disque,
  zéro dépendance externe, suffisant pour le volume attendu (quelques centaines d'utilisateurs max).
  Point à vérifier côté déploiement : le fichier SQLite doit vivre sur un **volume persistant** sous Kanopy.

---

## Ce qui existe aujourd'hui (POC)

- Flask + Slack Events API (`app_mention`)
- Un seul compte Google hardcodé (refresh token en env var)
- Une commande : `@Hex tasks` — convertit une liste de bullets en Google Tasks,
  dans une tasklist nommée d'après le channel
- Pas de persistance, pas d'authentification par utilisateur

---

## Architecture cible

### Stockage — SQLite

Deux tables simples :

```sql
CREATE TABLE users (
    slack_user_id     TEXT PRIMARY KEY,
    refresh_token_enc TEXT NOT NULL,   -- chiffré avec Fernet
    tasklist_name     TEXT,            -- NULL = utilise le nom du channel par défaut
    registered_at     TEXT NOT NULL
);
```

Le fichier SQLite (`hex.db`) est monté sur un volume persistant en production.
Les refresh tokens sont chiffrés avec `cryptography.fernet` avant écriture ;
la clé Fernet vit dans une variable d'environnement (`FERNET_KEY`).

### Nouvelles routes HTTP

| Route | Rôle |
|---|---|
| `GET /healthz` | Déjà existant |
| `POST /slack/events` | Déjà existant |
| `GET /oauth/google/callback` | Reçoit le code OAuth Google, échange et stocke le refresh token |

### Nouvelles commandes Slack

| Commande | Comportement |
|---|---|
| `@Hex register` | Envoie un lien OAuth Google en message éphémère |
| `@Hex unregister` | Supprime les credentials de l'utilisateur |
| `@Hex status` | Indique si l'utilisateur est enregistré, et quelle tasklist est configurée |
| `@Hex list` | Liste les tâches non terminées de la tasklist de l'utilisateur |
| `@Hex config tasklist <nom>` | Définit un nom de tasklist personnalisé (pour tous les channels) |
| `@Hex config tasklist default` | Remet le comportement par défaut (nom du channel) |

### Comportement de `@Hex tasks` (évolution)

- Si l'utilisateur **n'est pas enregistré**, répondre en éphémère :
  _"Tu n'es pas encore enregistré. Tape `@Hex register` pour connecter ton compte Google Tasks."_
- Si l'utilisateur **est enregistré**, créer les tâches dans **sa** tasklist Google
  (nom personnalisé s'il en a un, sinon nom du channel).

---

## Phases

### Phase 1 — Persistance (SQLite + chiffrement)

**Objectif :** poser les fondations sans rien casser.

- Ajouter `cryptography` aux dépendances
- Créer `db.py` : initialisation SQLite, fonctions CRUD pour les utilisateurs
  (`get_user`, `upsert_user`, `delete_user`)
- Ajouter `FERNET_KEY` à `config.py` et au `.env` local
- Migrer `google_tasks.py` pour utiliser le token de l'utilisateur
  plutôt que le token global (le token global reste en fallback le temps de la migration)

**Livrables :** `db.py`, tests manuels d'insert/read/delete

---

### Phase 2 — Enregistrement utilisateur (Google OAuth)

**Objectif :** chaque utilisateur connecte son propre compte Google.

**Flow complet :**
1. `@Hex register` → génère un `state` signé (JWT ou HMAC)
   contenant `slack_user_id` + timestamp d'expiration (10 min)
2. Envoie en éphémère l'URL OAuth Google avec `state`
3. L'utilisateur clique, autorise l'accès Google Tasks
4. Google redirige vers `/oauth/google/callback?code=...&state=...`
5. Le serveur vérifie le `state`, échange le `code` contre un `refresh_token`
6. Stocke le token chiffré en base
7. Envoie un DM de confirmation à l'utilisateur via Slack

**Nouvelles commandes à implémenter :**
- `RegisterCommand` (`@Hex register`)
- `UnregisterCommand` (`@Hex unregister`)
- `StatusCommand` (`@Hex status`)

**Prérequis configuration Google Cloud :**
- Créer un OAuth Client ID de type "Web application"
- Ajouter l'URI de callback dans les "Authorized redirect URIs"
  (`https://<domaine-kanopy>/oauth/google/callback`)
- Scopes requis : `https://www.googleapis.com/auth/tasks`

---

### Phase 3 — Commandes `list` et `config`

**Objectif :** permettre aux utilisateurs de consulter leurs tâches et de configurer leur tasklist.

**`@Hex list`**
- Récupère les tâches non terminées (`status != completed`) de la tasklist configurée
- Affiche en éphémère dans le thread (maximum 20 tâches pour éviter le spam)
- Si l'utilisateur n'est pas enregistré : renvoyer vers `@Hex register`

**`@Hex config tasklist <nom>`**
- Met à jour `tasklist_name` en base pour cet utilisateur
- Ce nom s'applique pour **tous les channels** (override global par utilisateur)
- `@Hex config tasklist default` remet `tasklist_name = NULL`

---

### Phase 4 — Déploiement Kanopy

**À investiguer avec l'équipe infra :**
- Type de workload Kanopy disponible (Deployment, StatefulSet ?)
- Comment monter un volume persistant pour `hex.db`
- Gestion des secrets (Kubernetes Secrets, Vault, autre ?)
- Domaine HTTPS public pour les callbacks OAuth

**Checklist technique :**
- `Dockerfile` (base Python 3.10-slim, Gunicorn, pas de serveur de dev Flask)
- Variables d'environnement requises :
  ```
  SLACK_BOT_TOKEN
  SLACK_SIGNING_SECRET
  SLACK_BOT_USER_ID       (optionnel, résolu dynamiquement sinon)
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  FERNET_KEY              (généré une fois : python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  DATABASE_PATH           (chemin vers hex.db sur le volume persistant, ex: /data/hex.db)
  PUBLIC_BASE_URL         (ex: https://hex-bot.mongodb.com, pour construire l'URL de callback OAuth)
  ```
- Health check sur `/healthz`

---

## Ordre des dépendances

```
Phase 1 (SQLite + chiffrement)
    └── Phase 2 (Google OAuth par utilisateur)
            └── Phase 3 (list + config)
                    └── Phase 4 (Kanopy)
```

---

## Ce qu'on ne fait PAS (hors scope)

- Multi-workspace Slack (un seul workspace : MongoDB)
- Interface web d'administration
- Notifications / rappels de tâches
- Intégration avec d'autres systèmes de tâches (Jira, etc.)
